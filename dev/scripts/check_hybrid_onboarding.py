"""Exercise fresh conversational onboarding with real bundled inference.

Run with the operator venv; all artifacts live outside the repository.
"""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid


def main():
    scratch = Path.home() / ".jaeger/scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="hybrid-check-", dir=scratch))
    model = Path(os.environ.get("JAEGER_SYSTEM_MODEL") or str(
        Path.home() / ".jaeger/models/qwen3-1.7b-system-q4_k_m/Qwen_Qwen3-1.7B-Q4_K_M.gguf"))
    env = dict(os.environ, JAEGER_STATE_DIR=str(root), JAEGER_HOME=str(root),
               JAEGER_INSTANCE_DIR=str(root / "instances/test"), JAEGER_NO_ATTACH="1",
               JAEGER_SYSTEM_MODEL=str(model), OLLAMA_HOST="http://127.0.0.1:1",
               JAEGER_OLLAMA_URL="http://127.0.0.1:1", HF_HUB_OFFLINE="1",
               TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    log = (root / "bridge.log").open("w")
    process = subprocess.Popen([sys.executable, "-c",
        "import faulthandler,runpy,os; trace=open(os.environ['JAEGER_STATE_DIR']+'/trace.log','w'); "
        "faulthandler.dump_traceback_later(20, repeat=True,file=trace); "
        "runpy.run_module('jaeger_ai.interfaces.bridge',run_name='__main__')", "test"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, env=env)
    frames = queue.Queue()

    def reader():
        for line in process.stdout:
            with (root / "frames.jsonl").open("a") as output:
                output.write(line)
            try:
                frame = json.loads(line)
                frames.put(frame)
            except ValueError:
                pass

    threading.Thread(target=reader, daemon=True).start()

    def receive(predicate):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            frame = frames.get(timeout=max(.1, deadline - time.monotonic()))
            if frame.get("type") == "fatal":
                raise RuntimeError(frame)
            if predicate(frame):
                return frame
        raise TimeoutError("bridge did not respond")

    def call(op, name, args=None):
        identifier = uuid.uuid4().hex
        process.stdin.write(json.dumps({"op": op, "id": identifier,
            "what" if op == "query" else "cmd": name, "args": args or {}}) + "\n")
        process.stdin.flush()
        result = receive(lambda frame: frame.get("id") == identifier)
        assert result.get("ok"), result
        return result.get("data")

    print(f"Artifacts: {root}", flush=True)
    try:
        assert receive(lambda f: f.get("type") == "ready")["agent"] == "setup"
        assert call("query", "first_boot")["status"] == "AWAITING_BENCH"
        print("PASS fresh install without configured agent", flush=True)
        call("command", "complete_setup", {"awake_provider": "in-process",
             "awake_model": str(model), "resume_onboarding": True})
        ready = receive(lambda f: f.get("type") == "agent_state" and f.get("state") in {"ready", "failed"})
        assert ready["state"] == "ready", ready
        print("PASS selected bundled model responds", flush=True)
        call("command", "first_boot_answer", {"question": "bench", "reply": "done",
             "recommendation": {"provider": "in-process", "awake": {"key": str(model)}}})
        call("command", "first_boot_answer", {"question": "character", "reply": "custom"})
        assert call("query", "first_boot")["status"] == "AWAITING_SOCIAL"
        call("command", "first_boot_answer", {"question": "social", "reply": "I am social."})
        if call("query", "first_boot")["status"] == "AWAITING_HESITANCE":
            call("command", "first_boot_answer", {"question": "hesitance", "reply": "No"})
        call("command", "first_boot_answer", {"question": "voice", "reply": "female"})
        call("command", "first_boot_answer", {"question": "q2", "reply": "We talk regularly."})
        speaker = None
        for _ in range(40):
            state = call("query", "first_boot")
            speaker = (state.get("turn") or {}).get("speaker")
            if speaker == "persona" or state.get("complete"):
                break
            if not (state.get("turn") or {}).get("awaits_reply"):
                call("command", "first_boot_answer", {"question": "tick", "reply": "ok"})
        assert speaker == "persona", state
        call("command", "first_boot_complete")
        assert call("query", "first_boot")["complete"]
        print("PASS character, calibration, naming, and durable completion", flush=True)
        process.stdin.write(json.dumps({"op": "send", "text": "Hello. Reply with a short greeting.",
                                       "session": "desktop-app"}) + "\n")
        process.stdin.flush()
        response = receive(lambda frame: frame.get("type") == "reply")
        assert response.get("text") and not response.get("error"), response
        print("PASS first agent conversation: " + response["text"][:160], flush=True)
    finally:
        if process.poll() is None:
            process.stdin.write('{"op":"quit"}\n')
            process.stdin.flush()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    main()
