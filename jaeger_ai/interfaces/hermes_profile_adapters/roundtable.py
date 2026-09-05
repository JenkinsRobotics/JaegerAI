#!/usr/bin/env python3
"""Roundtable adapter — C-debate mode between Hermes, Jaeger, and OpenClaw.

Flow:
  1. Your message goes to all three agents in parallel (Round 1)
  2. Each agent's response is collected
  3. Each agent gets the other two responses and gives a rebuttal (Round 2)
  4. Full debate streamed back via /v1/chat/completions SSE

OpenClaw uses WebSocket v4 protocol (not REST).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# ── Config ──────────────────────────────────────────────────────────────────

ADAPTER_PORT = int(os.environ.get("ROUNDTABLE_PORT", "8643"))
_timeout_setting = os.environ.get("ROUNDTABLE_MEMBER_TIMEOUT", "").strip()
MEMBER_TIMEOUT = float(_timeout_setting) if _timeout_setting else None
OPENCLAW_ADAPTER_URL = os.environ.get(
    "ROUNDTABLE_OPENCLAW_ADAPTER_URL", "http://192.168.64.1:8644"
).rstrip("/")
JAEGER_ADAPTER_URL = os.environ.get(
    "ROUNDTABLE_JAEGER_ADAPTER_URL", "http://127.0.0.1:8642"
).rstrip("/")

AGENT_LABELS = {
    "hermes": "🟦 Hermes",
    "jaeger": "🟩 Jaeger",
    "openclaw": "🦞 OpenClaw",
}
AGENT_ORDER = ("jaeger", "hermes", "openclaw")
TURN_MODES = ("ask", "collaborate", "quick", "review", "vote", "incident")
_OPERATIONAL_WORDS = re.compile(
    r"\b(?:down|broken|error|failed|fix|debug|diagnos|service|container|port|"
    r"network|config|file|repository|repo|deploy|install|tool|access|status|health)\w*\b",
    re.IGNORECASE,
)
_DEPLOYMENT_CONTEXT = """Canonical deployment facts supplied by the Roundtable orchestrator:
- The live Roundtable source is /Users/matthewjenkins/GitHub/JaegerAI/jaeger_ai/interfaces/hermes_profile_adapters/roundtable.py.
- Jaeger is native on macOS. Hermes WebUI and OpenClaw run in separate Apple containers.
- The active adapters are JaegerAI Python modules on ports 8642, 8643, and 8644.
- Files such as ~/workspace/roundtable-adapter.py are historical artifacts, not deployed source.
When auditing the installation, verify the canonical file or live health endpoint. Never label a claim
[Verified] when it came from memory, another member, an old transcript, or a similarly named file."""


def _turn_plan(message: str) -> dict:
    """Resolve mode, participants, and evidence requirements for one turn."""
    text = str(message or "").strip()
    mode = "ask"
    explicit = re.match(r"^/(ask|collaborate|quick|review|vote|incident)\b\s*", text, re.IGNORECASE)
    if explicit:
        mode = explicit.group(1).lower()
        text = text[explicit.end():].strip()
    elif re.search(r"\b(?:collaborate|work together|divide|who wants|figure it out)\b", text, re.IGNORECASE):
        mode = "collaborate"
    elif re.search(r"\b(?:review|critique|audit)\b", text, re.IGNORECASE):
        mode = "review"
    elif re.search(r"\b(?:vote|ballot|choose between)\b", text, re.IGNORECASE):
        mode = "vote"
    elif re.search(r"\b(?:incident|outage|production failure)\b", text, re.IGNORECASE):
        mode = "incident"

    mentioned = []
    lowered = text.lower()
    if "@all" in lowered:
        mentioned = list(AGENT_ORDER)
    else:
        mention_patterns = {
            "jaeger": r"@jaeger\b",
            "hermes": r"@hermes\b",
            "openclaw": r"@(?:openclaw|open-claw|open_claw)\b",
        }
        mentioned = [agent for agent in AGENT_ORDER if re.search(mention_patterns[agent], lowered)]
    participants = tuple(mentioned or AGENT_ORDER)
    if mode == "quick" and len(participants) > 1:
        participants = (_best_member(text),)
    return {
        "mode": mode,
        "message": text,
        "participants": participants,
        "evidence_required": bool(_OPERATIONAL_WORDS.search(text)),
    }


def _best_member(message: str) -> str:
    lowered = message.lower()
    if re.search(r"\b(?:openclaw|linux|ollama|messaging)\b", lowered):
        return "openclaw"
    if re.search(r"\b(?:hermes|container|coding|code)\b", lowered):
        return "hermes"
    return "jaeger"


def _member_prompt(plan: dict, agent: str) -> str:
    mode_instruction = {
        "ask": "Answer independently and directly.",
        "collaborate": (
            "Act as a teammate. State what part you can own. If you have relevant tools, "
            "perform one bounded read-only check now and report its result."
        ),
        "quick": "Give the shortest useful answer as the selected owner.",
        "review": "Review the request or proposal: identify strengths, defects, and a concrete correction.",
        "vote": "Give your recommendation, reasoning, and an explicit BALLOT line.",
        "incident": (
            "Treat this as an incident. Separate diagnostics, evidence gathering, and remediation; "
            "do not change services unless assigned as the remediation owner."
        ),
    }[plan["mode"]]
    evidence = ""
    if plan["evidence_required"]:
        evidence = (
            "\nEvidence discipline: prefix operational claims with [Verified], [Reported], "
            "[Inferred], or [Unknown]. Use [Verified] only for a tool result you obtained in "
            "this turn and name the check. Never translate a timeout into 'service down'."
        )
    return (
        f"{_DEPLOYMENT_CONTEXT}\n\nRoundtable mode: {plan['mode']}.\n"
        f"{mode_instruction}{evidence}\n\nUser: {plan['message']}"
    )


def _is_failed_answer(answer: str) -> bool:
    lowered = str(answer or "").lower()
    return (not lowered.strip() or " error:" in lowered or
            lowered.startswith("[") and "error:" in lowered or "no response" in lowered or
            lowered.strip() in {"llm request timed out.", "llm request timed out"})


def _choose_chair(participants: tuple[str, ...], session_id: str, message: str) -> str:
    digest = hashlib.sha256(f"{session_id}:{message}".encode("utf-8")).digest()
    return participants[digest[0] % len(participants)]

def _member_session_id(roundtable_session_id: str, agent: str) -> str:
    owner = roundtable_session_id or "anonymous"
    return uuid.uuid5(uuid.NAMESPACE_URL, f"jaeger-roundtable:{owner}:{agent}").hex

# ── Hermes client ────────────────────────────────────────────────────────────

def chat_hermes(message: str, session_id: str = "") -> str:
    """Send one turn to a real, named, natively resumable Hermes session."""
    executable = os.environ.get("ROUNDTABLE_HERMES_BIN") or shutil.which("hermes")
    if not executable:
        return "[Hermes error: executable not found]"
    stable_id = _member_session_id(session_id, "hermes")
    session_name = f"Roundtable {stable_id[:12]} — Hermes"
    command = [
        executable,
        "chat",
        "-c",
        session_name,
        "--create-if-missing",
        "-Q",
        "-q",
        message,
        "--source",
        "tool",
    ]
    try:
        proc = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=MEMBER_TIMEOUT,
            check=False,
        )
    except Exception as exc:
        return f"[Hermes error: {exc}]"
    output_lines = [
        line for line in (proc.stdout or "").splitlines()
        if not line.strip().lower().startswith("session_id:")
    ]
    output = "\n".join(output_lines).strip()
    if proc.returncode:
        detail = (proc.stderr or output).strip()
        return f"[Hermes error: {detail or 'command failed'}]"
    return output or "[Hermes: no response]"


# ── Native member adapters ──────────────────────────────────────────────────

def chat_openclaw(message: str, session_id: str = "") -> str:
    return _chat_adapter("OpenClaw", OPENCLAW_ADAPTER_URL, message, session_id)


def chat_jaeger(message: str, session_id: str = "") -> str:
    return _chat_adapter("Jaeger", JAEGER_ADAPTER_URL, message, session_id)


def _is_transient_member_error(exc: BaseException) -> bool:
    if isinstance(exc, (
        ConnectionError,
        TimeoutError,
        http.client.IncompleteRead,
        http.client.RemoteDisconnected,
        http.client.BadStatusLine,
    )):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in {502, 503, 504}
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        return _is_transient_member_error(exc.reason)
    return isinstance(exc, urllib.error.URLError)


def _chat_adapter(label: str, base_url: str, message: str, session_id: str = "") -> str:
    last_error: Exception | None = None
    attempts = 3
    for attempt in range(attempts):
        try:
            return _chat_adapter_once(label, base_url, message, session_id)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not _is_transient_member_error(exc) or attempt == attempts - 1:
                return f"[{label} error: {exc}]"
            time.sleep(0.4 * (attempt + 1))
    return f"[{label} error: {last_error}]"


def _chat_adapter_once(label: str, base_url: str, message: str, session_id: str = "") -> str:
    body = json.dumps({
        "model": label.lower(),
        "stream": True,
        "messages": [{"role": "user", "content": message}],
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": session_id,
        },
        method="POST",
    )
    chunks = []
    open_kwargs = {} if MEMBER_TIMEOUT is None else {"timeout": MEMBER_TIMEOUT}
    with urllib.request.urlopen(request, **open_kwargs) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            payload = json.loads(data)
            choice = (payload.get("choices") or [{}])[0]
            delta = (choice.get("delta") or {}).get("content")
            if delta:
                chunks.append(str(delta))
    return "".join(chunks) or f"[{label}: no response]"


# ── Debate orchestrator ──────────────────────────────────────────────────────

def _parallel_turns(
    prompts: dict[str, str], emit, heading: str, roundtable_session_id: str
) -> dict[str, str]:
    """Run one group-chat round and emit each answer as soon as it arrives."""
    callers = {"hermes": chat_hermes, "jaeger": chat_jaeger, "openclaw": chat_openclaw}
    results: dict[str, str] = {}
    lock = threading.Lock()
    emit(f"\n## {heading}\n\n")

    def ask(agent: str) -> None:
        try:
            answer = callers[agent](
                prompts[agent], _member_session_id(roundtable_session_id, agent)
            )
        except Exception as exc:
            answer = f"⚠️ Error: {exc}"
        with lock:
            results[agent] = answer
        emit(f"### {AGENT_LABELS[agent]}\n\n{answer}\n\n")

    active_callers = {agent: callers[agent] for agent in prompts}
    threads = [threading.Thread(target=ask, args=(agent,), daemon=True) for agent in active_callers]
    for thread in threads:
        thread.start()
    if MEMBER_TIMEOUT is None:
        for thread in threads:
            thread.join()
    else:
        deadline = time.monotonic() + MEMBER_TIMEOUT
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
    for agent in active_callers:
        if agent not in results:
            results[agent] = "⚠️ No response (timeout)"
            emit(f"### {AGENT_LABELS[agent]}\n\n{results[agent]}\n\n")
    return results


def run_debate_stream(user_message: str, emit, session_id: str = "") -> None:
    """Stream a mode-aware group turn followed by strict consensus."""
    plan = _turn_plan(user_message)
    participants = plan["participants"]
    participant_labels = ", ".join(AGENT_LABELS[agent] for agent in participants)
    emit(
        f"## 🎯 Your Question\n\n{plan['message']}\n\n"
        f"**Mode:** {plan['mode']}  \n**Participants:** {participant_labels}\n"
    )
    round1 = _parallel_turns(
        {agent: _member_prompt(plan, agent) for agent in participants}, emit,
        "Round 1 — Everyone Answers", session_id,
    )
    if plan["mode"] == "quick":
        return
    transcript = "\n\n".join(
        f"{AGENT_LABELS[agent]}:\n{answer}" for agent, answer in round1.items()
    )
    discussion_instruction = {
        "ask": "Respond to peers, correct errors, and seek common ground.",
        "collaborate": "Coordinate ownership, compare evidence, and propose the next executable action.",
        "review": "Resolve review findings: confirm valid defects and reject unsupported criticism.",
        "vote": "Review the ballots, then keep or revise your vote with a final BALLOT line.",
        "incident": "Compare diagnostic evidence and assign a remediation owner. Flag unverified causes.",
    }[plan["mode"]]
    discussion_prompt = (
        f"{_DEPLOYMENT_CONTEXT}\n\nCurrent user request: {plan['message']}\n\n"
        f"Current-round answers:\n{transcript}\n\n"
        f"One group discussion round: {discussion_instruction} Be concise. Do not claim "
        "another member agrees unless their text explicitly says so."
    )
    round2 = _parallel_turns(
        {agent: discussion_prompt for agent in participants if not _is_failed_answer(round1.get(agent, ""))}, emit,
        "Round 2 — Group Discussion", session_id,
    )
    discussion = "\n\n".join(
        f"{AGENT_LABELS[agent]}:\n{answer}" for agent, answer in round2.items()
    )
    emit("\n## 🤝 Decision Summary\n\n")
    callers = {"hermes": chat_hermes, "jaeger": chat_jaeger, "openclaw": chat_openclaw}
    responsive = [agent for agent in participants if not _is_failed_answer(round2.get(agent, ""))]
    if not responsive:
        emit("No successful discussion answers. No consensus was reached; native sessions are preserved.\n")
        return
    chair = _choose_chair(tuple(responsive), session_id, plan["message"])
    consensus_prompt = (
        f"{_DEPLOYMENT_CONTEXT}\n\nYou are the neutral Roundtable chair. Mode: {plan['mode']}.\n"
        f"User request: {plan['message']}\n\nInitial answers:\n{transcript}\n\n"
        f"Discussion:\n{discussion}\n\nThere are {len(participants)} participants and "
        f"{len(responsive)} responsive discussion answers. Produce exactly these sections: "
        "Unanimous agreement; Majority position; Minority objections; Evidence ledger; "
        "Unknown or unverified; Recommended next action and owner. A claim is unanimous only "
        "when every selected participant explicitly supports it. A failed or absent participant "
        "prevents unanimous agreement. Never infer service outage "
        "from timeout. Never say tools were used unless a member reports a concrete tool result."
    )
    consensus = callers[chair](
        consensus_prompt, _member_session_id(session_id, chair)
    )
    if _is_failed_answer(consensus):
        for fallback in responsive:
            if fallback == chair:
                continue
            consensus = callers[fallback](
                consensus_prompt, _member_session_id(session_id, fallback)
            )
            if not _is_failed_answer(consensus):
                chair = fallback
                break
    emit(f"**Chair:** {AGENT_LABELS[chair]}\n\n")
    emit(consensus + "\n")


def run_debate(user_message: str, session_id: str = "") -> str:
    parts: list[str] = []
    run_debate_stream(user_message, parts.append, session_id)
    return "".join(parts)


# ── REST API Server ────────────────────────────────────────────────────────

_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()


class RoundtableHandler(BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path in ("/health", "/v1/health", "/health/detailed"):
            self._send_json(200, {"ok": True, "status": "ready", "agents": list(AGENT_LABELS.keys())})
        elif self.path == "/v1/capabilities":
            self._send_json(200, {"streaming": True, "models": [{"id": "roundtable", "name": "Roundtable Debate", "provider": "roundtable"}], "approval": False})
        elif re.match(r"^/v1/runs/([\w-]+)(?:/events)?$", self.path):
            run_id = re.match(r"^/v1/runs/([\w-]+)", self.path).group(1)
            self._handle_get_events(run_id)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/v1/runs":
            self._handle_create_run()
        elif self.path == "/v1/chat/completions":
            self._handle_chat_completions()
        elif re.match(r"^/v1/runs/([\w-]+)/cancel$", self.path):
            run_id = self.path.split("/")[-2]
            with _runs_lock:
                if run_id in _runs: _runs[run_id]["status"] = "cancelled"
            self._send_json(200, {"run_id": run_id, "status": "cancelled"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        for h in [("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                   ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Hermes-Session-Id, X-Hermes-Session-Key")]:
            self.send_header(h[0], h[1])
        self.end_headers()

    def _handle_chat_completions(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        messages = body.get("messages", [])
        session_id = str(
            self.headers.get("X-Hermes-Session-Id")
            or body.get("session_id")
            or ""
        )
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                user_msg = " ".join(p.get("text", "") for p in content if isinstance(p, dict)) if isinstance(content, list) else str(content)
                break

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

        result_holder = {"done": False}
        output_queue: queue.Queue[str] = queue.Queue()
        def _run():
            try: run_debate_stream(user_msg, output_queue.put, session_id)
            except Exception as e: output_queue.put(f"\n⚠️ Roundtable error: {e}\n")
            finally: result_holder["done"] = True

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
        try:
            self.wfile.write(b": debate starting\n\n")
            self.wfile.flush()
            while not result_holder["done"] or not output_queue.empty():
                try:
                    text = output_queue.get(timeout=1)
                except queue.Empty:
                    self.wfile.write(b": waiting\n\n")
                    self.wfile.flush()
                    continue
                chunk = {"id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()),
                         "model": "roundtable", "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()

            final = {"id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()),
                     "model": "roundtable", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _handle_create_run(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}
        message = body.get("input") or body.get("message") or ""
        session_id = str(
            body.get("session_id")
            or self.headers.get("X-Hermes-Session-Id")
            or ""
        )
        if isinstance(message, list):
            message = " ".join(p.get("content", "") if isinstance(p, dict) else str(p) for p in message)

        run_id = uuid.uuid4().hex[:16]
        with _runs_lock:
            _runs[run_id] = {"id": run_id, "status": "running", "input": message, "session_id": session_id, "created_at": time.time(), "result": "", "error": ""}

        def _run():
            try:
                def emit(text):
                    with _runs_lock:
                        if _runs[run_id]["status"] == "cancelled":
                            raise RuntimeError("Run cancelled")
                        _runs[run_id]["result"] += text
                run_debate_stream(message, emit, session_id)
                with _runs_lock:
                    if _runs[run_id]["status"] == "running":
                        _runs[run_id]["status"] = "completed"
            except Exception as e:
                with _runs_lock:
                    if _runs[run_id]["status"] != "cancelled":
                        _runs[run_id].update({"status": "failed", "error": str(e)})

        threading.Thread(target=_run, daemon=True).start()
        self._send_json(200, {"run_id": run_id, "status": "running"})

    def _handle_get_events(self, run_id: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        offset = 0
        while True:
            with _runs_lock:
                run = _runs.get(run_id)
                if not run:
                    self.wfile.write(b'data: {"event": "error", "message": "run not found"}\n\n')
                    break
                status, result, error = run["status"], run.get("result", ""), run.get("error", "")
            if len(result) > offset:
                self.wfile.write(f'data: {json.dumps({"event": "message.delta", "delta": result[offset:]})}\n\n'.encode())
                offset = len(result)
            if status == "completed":
                self.wfile.write(f'data: {json.dumps({"event": "run.completed", "run_id": run_id})}\n\n'.encode())
                break
            elif status == "failed":
                self.wfile.write(f'data: {json.dumps({"event": "run.failed", "error": error})}\n\n'.encode())
                break
            elif status == "cancelled":
                self.wfile.write(b'data: {"event": "run.cancelled"}\n\n')
                break
            self.wfile.write(b": heartbeat\n\n")
            self.wfile.flush()
            time.sleep(1)
        self.wfile.flush()

    def _send_json(self, code: int, data: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        body = json.dumps(data).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[roundtable] {args[0]}")


if __name__ == "__main__":
    print(f"[roundtable] C-Debate adapter on :{ADAPTER_PORT}")
    print("[roundtable] Hermes: Jaeger delegate registry")
    print(f"[roundtable] Jaeger adapter: {JAEGER_ADAPTER_URL}")
    print(f"[roundtable] OpenClaw adapter: {OPENCLAW_ADAPTER_URL}")
    server = ThreadingHTTPServer(("0.0.0.0", ADAPTER_PORT), RoundtableHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[roundtable] Shutting down")
        server.shutdown()
