"""Benchmark the native bridge + attached engine using VoiceLLM's exact cases.

Creates isolated application state; never boots or edits the live instance.
No microphone, camera or speaker is opened. This is a post-endpoint semantic
benchmark, not a live duplex certification. Raw results use the shared scorer.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-instance", type=Path, required=True)
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--audio-dir", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-runner", type=Path, default=Path(__file__).resolve().parents[2] / "packages/jaeger-agent/scripts/benchmark_multimodal_candidate.py")
    parser.add_argument("--ids", default="")
    parser.add_argument("--agentic-tools", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--workflow", action="store_true", help="also verify real file creation/readback in the isolated workspace")
    parser.add_argument("--mode-switch", action="store_true", help="verify conversation recall across agentic/chatbot/agentic switches")
    parser.add_argument("--cancel-turn", action="store_true", help="cancel real inference, then verify the same session can answer again")
    parser.add_argument("--installed-vad", action="store_true", help="use the VAD packaged with the installed agent instead of a developer model path")
    parser.add_argument("--native-turns", action="store_true", help="verify native image payloads and tools-mode continuity")
    args = parser.parse_args()

    import yaml
    from jaeger_agent import MultimodalAgent

    from jaeger_ai.core.bench.scenarios import build_hermetic_instance
    from jaeger_ai.interfaces.bridge import attached_face_socket_path
    from jaeger_ai.interfaces.pyside6.multimodal.remote_runtime import (
        AttachedAgentRuntime,
    )
    from jaeger_ai.interfaces.pyside6.multimodal.worker import BorrowedRuntime

    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    hermetic = build_hermetic_instance(args.source_instance, parent=Path("/tmp"))
    config_path = hermetic.instance_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config.setdefault("model", {})["model_path"] = str(args.model_path.resolve())
    if args.installed_vad:
        from jaeger_agent import MultimodalConfig
        config.setdefault("multimodal", {})["silero_model_path"] = MultimodalConfig().silero_model_path
    # Sampling and context are read from the *actual* application config.
    args.ctx = config["model"].get("n_ctx", config["model"].get("ctx", 32768))
    args.max_tokens = config["model"].get("max_tokens", 1024)
    args.temperature = 0.0  # LocalLlamaAdapter's actual default in runtime_bridge
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    spec = importlib.util.spec_from_file_location("candidate_benchmark", args.candidate_runner)
    candidate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = candidate
    spec.loader.exec_module(candidate)

    env = dict(os.environ, JAEGER_INSTANCE_DIR=str(hermetic.instance_dir),
               JAEGER_BENCH_NEUTRAL_IDENTITY="1", JAEGER_TOOLSET_SCOPING="1")
    ready = threading.Event()
    native_responses = queue.Queue()
    frames = []
    remote = None
    started = time.perf_counter()
    with args.output.with_suffix(".bridge.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "jaeger_ai.interfaces.bridge", "benchmark"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, env=env,
        )

        def read_frames():
            for raw in process.stdout:
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                frames.append(frame)
                if ((frame.get("type") == "result" and frame.get("id") == "native-stt-probe")
                        or (frame.get("type") == "reply" and str(frame.get("id", "")).startswith("release-native-"))):
                    native_responses.put(frame)
                if frame.get("type") == "agent_state" and frame.get("state") in {"ready", "failed"}:
                    ready.set()

        reader = threading.Thread(target=read_frames, daemon=True)
        reader.start()
        result = None
        try:
            if not ready.wait(240):
                raise TimeoutError("application bridge did not finish boot within 240s")
            remote = AttachedAgentRuntime(attached_face_socket_path(hermetic.instance_dir), timeout=180)
            health = remote.health()
            print(f"Bridge ready after {time.perf_counter() - started:.2f}s: {health}", flush=True)
            remote.configure_vision(True)
            app_boot_ms = (time.perf_counter() - started) * 1000
            # Exercise the actual NDJSON command used by native Chat/Avatar,
            # in addition to the Unix-socket path used by the multimodal face.
            native_audio = candidate._read_wav(args.audio_dir / "q00.wav")
            native_started = time.perf_counter()
            process.stdin.write(json.dumps({
                "op": "command", "cmd": "transcribe_audio", "id": "native-stt-probe",
                "args": {"pcm": base64.b64encode(native_audio.astype("<f4").tobytes()).decode("ascii"),
                         "sample_rate": 16000},
            }) + "\n")
            process.stdin.flush()
            # A fresh installation initializes Kokoro and compiles Whisper's
            # Metal kernels here. Apply the same cold-start budget as audio
            # requests on the attached face; report actual latency below.
            native_probe = native_responses.get(timeout=180)
            native_probe["elapsed_ms"] = round((time.perf_counter() - native_started) * 1000, 2)
            if not native_probe.get("ok"):
                raise RuntimeError(f"native dictation probe failed: {native_probe}")
            print(f"Native dictation probe: {native_probe}", flush=True)

            native_turns = []
            if args.native_turns:
                image_data = "data:image/png;base64," + base64.b64encode(
                    (args.benchmark_dir / "assets/red_square.png").read_bytes()).decode()
                for number, (tools_enabled, prompt, expected, image) in enumerate((
                    (False, "Remember my reference code COPPER-ORBIT-314. Reply OK.", [], None),
                    (True, "Repeat my reference code. Reply only with the code.", ["COPPER-ORBIT-314"], None),
                    (False, "What is the central shape and its color?", ["red", "square"], image_data),
                )):
                    request = {"op": "send", "id": f"release-native-{number}",
                               "session": "native-multimodal-test", "text": prompt,
                               "agentic_tools": tools_enabled, "output_mode": "text",
                               "client_owned_speech": True}
                    if image:
                        request["content"] = [{"type": "text", "text": prompt},
                                              {"type": "image_url", "image_url": {"url": image}}]
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                    answer = native_responses.get(timeout=180)
                    ok = not answer.get("error") and all(
                        term.lower() in answer.get("text", "").lower() for term in expected)
                    native_turns.append({"reply": answer, "ok": ok})
                print(f"Native multimodal turns: {native_turns}", flush=True)

            def factory(**kwargs):
                kwargs.pop("runtime_config", None)
                kwargs["want_vision"] = False  # projector is beside bridge-owned Gemma
                kwargs["config"] = health["multimodal_config"]
                engine = MultimodalAgent(runtime=BorrowedRuntime(remote, agentic_tools=args.agentic_tools), **kwargs)
                engine.node_stt = remote.make_stt_node(engine.config.stt_model)
                engine.node_tts = remote.make_tts_node()
                engine._stt_lock = engine.node_stt._lock
                return engine

            result = candidate.run(args, engine_factory=factory)
            # A clean process exit is insufficient: use the reference scorer
            # on raw responses and fail the command on a wrong answer.
            scorer = candidate._load_benchmark(args.benchmark_dir)
            result["summary"] = scorer.score_result(result)
            spoken = [row for row in result["cases"] if row.get("modality") == "spoken"]
            result["spoken_audio_complete"] = all(
                (row.get("audio_samples") or 0) > 0 for row in spoken
            )
            result["engine_load_ms"] = result["load_ms"]
            result["bridge_boot_and_vision_ms"] = round(app_boot_ms, 2)
            result["load_ms"] = round(app_boot_ms + result["engine_load_ms"], 2)
            result["engine"] = "jaeger-ai-attached-bridge"
            result["configuration"]["instance_config"] = config.get("model", {})
            result["configuration"]["isolated_instance"] = str(hermetic.instance_dir)
            result["configuration"]["benchmark_boundary"] = "completed endpoint; no live devices"
            result["native_dictation_probe"] = native_probe
            result["native_turns"] = native_turns
            for requested, key in ((args.workflow, "workflow"),
                                   (args.mode_switch, "mode_switch"),
                                   (args.cancel_turn, "cancellation")):
                if requested:
                    result[key] = {"ok": False, "error": "check did not complete"}
            if args.workflow:
                if not args.agentic_tools:
                    raise ValueError("--workflow requires agentic mode")
                activity = []
                remote.set_event_sink(activity.append)
                artifact = hermetic.instance_dir / "workspace/release_review_smoke.txt"
                workflow_started = time.perf_counter()
                reply = remote.run_multimodal_turn(
                    "Use write_file with path='workspace/release_review_smoke.txt' "
                    "to create a file containing exactly READY-012. "
                    "Then use read_file with that same relative path to read the file back "
                    "and report its exact contents. "
                    "Do not access any other files.",
                    text="Create and verify the isolated release-test artifact.",
                    system_prompt="[OUTPUT:TEXT] Use text output only for this verification.",
                    session_key="release-workflow",
                )
                tools_used = sorted({f.get("name", "") for f in activity if f.get("type") == "tool"})
                content = artifact.read_text() if artifact.is_file() else None
                result["workflow"] = {"reply": reply, "tools": tools_used, "artifact": str(artifact),
                                      "content": content, "elapsed_s": time.perf_counter() - workflow_started,
                                      "ok": content is not None and content.strip() == "READY-012"
                                            and "READY-012" in reply.get("text", "")
                                            and {"write_file", "read_file"}.issubset(tools_used)
                                            and not reply.get("error")}
                print(f"Workflow: {result['workflow']}", flush=True)
            if args.mode_switch:
                marker = "ORBIT-CEDAR-712"
                answers = []
                for mode, prompt in (
                    (True, f"Remember my test reference code: {marker}. Reply OK."),
                    (False, "What is my test reference code? Reply with only the code."),
                    (True, "Repeat my test reference code. Reply with only the code."),
                ):
                    method = remote.run_multimodal_turn if mode else remote.run_chatbot_multimodal_turn
                    answers.append(method(prompt, text=prompt, system_prompt="Be concise.",
                                          session_key="release-mode-switch"))
                result["mode_switch"] = {
                    "answers": answers,
                    "ok": all(not answer.get("error") for answer in answers)
                          and all(marker in answer.get("text", "") for answer in answers[1:]),
                }
                print(f"Mode continuity: {result['mode_switch']}", flush=True)
            if args.cancel_turn:
                from jaeger_agent.core.cancellation import turn_cancellation
                from jaeger_agent.core.outputs import multimodal_output_scope
                cancelled = threading.Event()
                attempted = threading.Event()
                box = {}

                def long_turn():
                    try:
                        with turn_cancellation(cancelled), multimodal_output_scope():
                            attempted.set()
                            box["reply"] = remote.run_multimodal_turn(
                                "Write 400 numbered sentences about imaginary cloud shapes. Do not use tools.",
                                text="Write 400 numbered sentences about imaginary cloud shapes. Do not use tools.",
                                system_prompt="Be concise.", session_key="release-cancellation")
                    except Exception as exc:
                        box["error"] = str(exc)

                task = threading.Thread(target=long_turn, daemon=True)
                task.start()
                attempted.wait(2)
                time.sleep(1)
                stop_started = time.perf_counter()
                cancelled.set()
                task.join(10)
                cancel_seconds = time.perf_counter() - stop_started
                if task.is_alive():
                    raise RuntimeError("cancelled inference did not settle within 10 seconds")
                with multimodal_output_scope():
                    recovery = remote.run_multimodal_turn(
                        "Reply with only AFTER-CANCEL.", text="Reply with only AFTER-CANCEL.",
                        system_prompt="Be concise.", session_key="release-cancellation")
                result["cancellation"] = {
                    "cancel_seconds": cancel_seconds, "cancelled_turn": box,
                    "recovery": recovery,
                    "ok": not box.get("reply", {}).get("text")
                          and not recovery.get("error") and "AFTER-CANCEL" in recovery.get("text", ""),
                }
                print(f"Cancellation: {result['cancellation']}", flush=True)
        finally:
            if remote is not None:
                remote.close()
            try:
                process.stdin.write('{"op":"quit"}\n')
                process.stdin.flush()
                process.stdin.close()
                exit_code = process.wait(timeout=45)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                exit_code = process.returncode
            reader.join(timeout=2)
            process.stdout.close()
            lifecycle = {"exit_code": exit_code, "bye_received": any(f.get("type") == "bye" for f in frames),
                         "isolated_instance": str(hermetic.instance_dir)}
            args.output.with_suffix(".lifecycle.json").write_text(json.dumps(lifecycle, indent=2) + "\n")
            if result is not None:
                result["lifecycle"] = lifecycle
                args.output.write_text(json.dumps(result, indent=2) + "\n")
            print(f"Lifecycle: {lifecycle}", flush=True)
    return 0 if (result is not None and exit_code == 0
                 and result["summary"]["n"] > 0
                 and result["summary"]["correct"] == result["summary"]["n"]
                 and result["spoken_audio_complete"]
                 and not any(r.get("error") for r in result["cases"])
                 and all(t["ok"] for t in result.get("native_turns", []))
                 and result.get("workflow", {}).get("ok", True)
                 and result.get("cancellation", {}).get("ok", True)
                 and result.get("mode_switch", {}).get("ok", True)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
