#!/usr/bin/env python3
"""Live chat through the main screen's own origin (the same routes GatewayClient uses):
POST /v1/sessions, GET /v1/sessions/{id}/stream (SSE), POST /v1/sessions/{id}/turns.
Loopback only; carries no token itself (the dev token proxy behind the UI origin adds it).
Prints the gateway's active runtime model and the model that answered. Default text: Scripts/live-prompt.txt (one
realistic prompt: a long markdown answer with headings, a list, a table, a code fence and >=2 read-only tool calls);
with it, the run fails unless the reply has a fenced code block AND a table AND the stream shows >=2 completed tools.
--expect-fence: also require a fence for a custom text. --trace: print the non-text event sequence (tool, progress)."""
import os
import json
import sys
import threading
import time
import urllib.request
import uuid

ORIGIN = next((a for a in sys.argv[1:] if not a.startswith("--")), "http://127.0.0.1:18800")
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live-prompt.txt")
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
DEFAULT_PROMPT = len(ARGS) < 2 or ARGS[1] in ("", "-")
TEXT = open(PROMPT_FILE).read().strip() if DEFAULT_PROMPT else ARGS[1]
TIMEOUT = float(ARGS[2]) if len(ARGS) > 2 else 300
assert ORIGIN.startswith("http://127.0.0.1:"), "loopback only"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ORIGIN + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")[:200].decode(errors="replace")


status, rt = call("GET", "/v1/runtime/models")
active = (rt.get("active") if isinstance(rt, dict) else None) or rt
print(f"GET /v1/runtime/models -> {status} active={str(active)[:160]}")
status, agents = call("GET", "/v1/agents")
names = [a.get("name") or a.get("label") or a.get("id") for a in (agents.get("agents", agents) if isinstance(agents, dict) else agents or [])] if status == 200 else agents
print(f"GET /v1/agents -> {status} {str(names)[:160]}")
sid = str(uuid.uuid4())
status, row = call("POST", "/v1/sessions", {"session_id": sid, "source": "webui", "title": "live chat check"})
print(f"POST /v1/sessions -> {status} {str(row)[:120]}")
if status >= 300:
    sys.exit(1)

events, reply, done = [], [], threading.Event()
finish = {}
trace = []


def stream():
    req = urllib.request.Request(f"{ORIGIN}/v1/sessions/{sid}/stream", headers={"Accept": "text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            name, data = None, []
            for raw in r:
                line = raw.decode(errors="replace").rstrip("\n").rstrip("\r")
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif line == "" and data:
                    try:
                        obj = json.loads("\n".join(data))
                    except ValueError:
                        obj = {}
                    ev = name or (obj.get("event") if isinstance(obj, dict) else None) or "?"
                    events.append(ev)
                    p = obj.get("payload", obj) if isinstance(obj, dict) else {}
                    if "--trace" in sys.argv and ev not in ("turn.delta", "turn.reasoning"):
                        d = p.get("data", p) if isinstance(p, dict) else {}
                        d = d if isinstance(d, dict) else {}
                        bits = {k: str(d[k])[:60] for k in ("tool", "message", "status", "title") if d.get(k)}
                        trace.append(f"{ev}{' ' + str(bits) if bits else ''}")
                    if ev == "turn.delta":
                        if not reply and "--raw" in sys.argv:
                            print("first delta frame:", json.dumps(obj)[:300])
                        d = p.get("data", p) if isinstance(p, dict) else {}
                        reply.append(str(d.get("delta") or d.get("text") or d.get("content") or ""))
                    if ev in ("turn.finish", "turn.failed", "turn.cancelled", "turn.unknown", "turn.reconciled"):
                        if isinstance(p, dict):
                            finish.update(p.get("data", p) if isinstance(p.get("data", p), dict) else {})
                        if ev != "turn.finish":
                            reply.append(f"[{ev}: {str(p.get('error') or p.get('message') or '')[:200]}]")
                        done.set()
                        return
                    name, data = None, []
    except Exception as exc:  # noqa: BLE001
        events.append(f"stream error: {type(exc).__name__}: {exc}")
        done.set()


t = threading.Thread(target=stream, daemon=True)
t.start()
time.sleep(1.0)
t0 = time.time()
status, receipt = call("POST", f"/v1/sessions/{sid}/turns", {"text": TEXT, "request_id": str(uuid.uuid4())})
print(f"POST /v1/sessions/{{id}}/turns -> {status} {str(receipt)[:160]}")
done.wait(TIMEOUT)
seen = sorted(set(events))
print(f"stream events: {seen}")
if trace:
    print("trace:\n  " + "\n  ".join(trace[:30]))
text = ''.join(reply).strip()
models = {k: v for k, v in finish.items() if "model" in k or k in ("provider", "fallback_used", "fallback")}
print(f"answered by: {models or 'not reported in turn.finish'}")
print(f"reply after {time.time() - t0:.1f}s: {text[:600]!r}")
ok = bool(text) and not text.startswith("[")
fenced = "```" in text or "~~~" in text
table = any(set(line.replace("|", "").replace(":", "").strip()) == {"-"} and line.count("|") >= 2 for line in text.splitlines())
tools_done = sum(1 for e in events if e in ("tool.completed", "tool.done"))
headings = sum(1 for line in text.splitlines() if line.startswith("## "))
print(f"checks: fence={fenced} table={table} tool.completed={tools_done} headings={headings} chars={len(text)}")
if DEFAULT_PROMPT:
    ok = ok and fenced and table and tools_done >= 2
elif "--expect-fence" in sys.argv:
    ok = ok and fenced
sys.exit(0 if ok else 1)
