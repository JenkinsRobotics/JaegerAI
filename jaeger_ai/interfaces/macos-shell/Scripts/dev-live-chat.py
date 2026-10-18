#!/usr/bin/env python3
"""Live chat through the main screen's own origin (the same routes GatewayClient uses):
POST /v1/sessions, GET /v1/sessions/{id}/stream (SSE), POST /v1/sessions/{id}/turns.
Loopback only; carries no token itself (the dev token proxy behind the UI origin adds it).
Prints the gateway's active runtime model and the model that answered. --expect-fence: fail unless the
reply contains a fenced code block."""
import json
import sys
import threading
import time
import urllib.request
import uuid

ORIGIN = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18800"
TEXT = sys.argv[2] if len(sys.argv) > 2 else "Reply with exactly one word: pong"
TIMEOUT = float(sys.argv[3]) if len(sys.argv) > 3 else 240
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
text = ''.join(reply).strip()
models = {k: v for k, v in finish.items() if "model" in k or k in ("provider", "fallback_used", "fallback")}
print(f"answered by: {models or 'not reported in turn.finish'}")
print(f"reply after {time.time() - t0:.1f}s: {text[:600]!r}")
ok = bool(text) and not text.startswith("[")
if "--expect-fence" in sys.argv:
    fenced = "```" in text or "~~~" in text
    print(f"fenced code block in reply: {fenced}")
    ok = ok and fenced
sys.exit(0 if ok else 1)
