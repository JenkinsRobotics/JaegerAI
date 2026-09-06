import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Run, Runs, RunsHTTP, jaeger_turn


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.005)
    assert predicate()


def test_approval_is_run_scoped_and_single_use(tmp_path):
    run = Run(tmp_path, "session", "hello")
    other = Run(tmp_path, "other", "hello")
    answers = []
    thread = threading.Thread(target=lambda: answers.append(run.request_approval("test", choices=("once", "deny"))))
    thread.start()
    wait_for(lambda: bool(run.pending))
    approval_id = next(iter(run.pending))
    try:
        with pytest.raises(KeyError):
            other.approve(approval_id, "once")
        with pytest.raises(ValueError):
            run.approve(approval_id, "always")
        run.approve(approval_id, "once")
        with pytest.raises(KeyError):
            run.approve(approval_id, "once")
    finally:
        thread.join(3)
    assert answers == ["once"]


def test_approval_timeout_denies(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_WEBUI_APPROVAL_TIMEOUT", ".01")
    run = Run(tmp_path, "session", "hello")
    assert run.request_approval("test") == "deny"
    assert not run.pending


def test_cancellation_unblocks_approval_and_does_not_complete_late(tmp_path):
    answers = []
    def backend(run, workspace):
        answers.append(run.request_approval("test"))
        run.cancel_confirmed = True
        return "Late answer"
    runs = Runs(tmp_path, backend)
    info = runs.start("session", "hello")
    run = runs.get(info["run_id"])
    wait_for(lambda: bool(run.pending))
    run.cancel()
    wait_for(lambda: run.status == "cancelled")
    assert answers == ["deny"]
    assert not run.output
    run.emit("run.completed", output="cannot resurrect")
    assert run.status == "cancelled"


def test_same_session_busy_until_native_turn_exits(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def backend(run, workspace):
        entered.set()
        release.wait(3)
        return "done"
    runs = Runs(tmp_path, backend)
    run = runs.get(runs.start("session", "hello")["run_id"])
    assert entered.wait(2)
    try:
        run.cancel()
        with pytest.raises(RuntimeError, match="session_busy"):
            runs.start("session", "duplicate")
        assert run.status == "cancelling"
    finally:
        release.set()
    wait_for(lambda: run.status == "completed")
    assert not run.snapshot()["cancellation_confirmed"]
    assert run.output == "done"  # Native completion won; do not invent an abort.


def test_restart_keeps_receipt_never_replays_work(tmp_path):
    run = Run(tmp_path, "session", "hello")
    run.emit("message.delta", delta="partial")
    calls = []
    recovered = Runs(tmp_path, lambda *a: calls.append(a)).get(run.id)
    assert recovered["status"] == "interrupted"
    assert recovered["output"] == "partial"
    assert recovered["events"][-1]["error_category"] == "adapter_restarted"
    assert not calls
    assert (tmp_path / f"{run.id}.json").stat().st_mode & 0o777 == 0o600


def test_jaeger_translates_native_events_and_targets_cancellation(tmp_path, monkeypatch):
    controls = []
    class Bridge:
        def __init__(self, instance):
            assert instance == "jaeger"
        def control(self, op, **payload):
            controls.append((op, payload))
        def turn(self, message, session, event, approval, **kwargs):
            assert kwargs["turn_id"] == run.id
            event({"type": "state"})
            event({"type": "tool", "phase": "start", "name": "read", "args": {"path": "x"}})
            event({"type": "tool", "phase": "done", "name": "read"})
            event({"type": "delta", "text": "hello"})
            run.cancel()
            return {"text": "hello"}
    monkeypatch.setattr("jaeger_ai.interfaces.hermes_webui_adapter.bridge_client.BridgeClient", Bridge)
    run = Run(tmp_path, "session", "hello")
    assert jaeger_turn(run) == "hello"
    assert controls == [("cancel", {"turn_id": run.id})]
    assert [e["event"] for e in run.events][1:4] == ["tool.started", "tool.completed", "message.delta"]


def test_http_runs_approval_replay_and_missing_run(tmp_path):
    def backend(run, workspace):
        answer = run.request_approval("A harmless fake tool")
        run.emit("tool.started", tool="fake")
        run.emit("tool.completed", tool="fake")
        return answer
    runs = Runs(tmp_path, backend)
    class Handler(RunsHTTP, BaseHTTPRequestHandler):
        def native_runs(self): return runs
        def native_key(self): return "test-token"
        def do_GET(self): self.native_route("GET")
        def do_POST(self): self.native_route("POST")
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    def request(path, body=None, headers=None):
        return urlopen(Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json", "Authorization": "Bearer test-token", **(headers or {})}), timeout=3)
    try:
        with request("/v1/capabilities") as response:
            assert json.load(response)["features"]["approval_identity_v1"]
        with request("/v1/runs", {"session_id": "session", "input": "hi"}) as response:
            rid = json.load(response)["run_id"]
        run = runs.get(rid)
        wait_for(lambda: bool(run.pending))
        with request(f"/v1/runs/{rid}/approval", {"approval_id": next(iter(run.pending)), "choice": "deny"}) as response:
            assert json.load(response)["ok"]
        wait_for(lambda: run.status == "completed")
        with request(f"/v1/runs/{rid}/events", headers={"Last-Event-ID": f"{rid}:2"}) as response:
            text = response.read().decode()
        assert '"event": "approval.request"' not in text
        assert '"event": "run.completed"' in text
        with request(f"/v1/runs/{rid}") as response:
            assert json.load(response)["status"] == "completed"
        with pytest.raises(HTTPError) as exc:
            request("/v1/runs/doesnotexist/events")
        assert exc.value.code == 404
        with pytest.raises(HTTPError) as exc:
            request(f"/v1/runs/{rid}/stop", {}, headers={"Authorization": "Bearer wrong"})
        assert exc.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_host_workspace_translation_rejects_escape():
    from pathlib import Path
    from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import host_workspace
    assert host_workspace("/mnt/host/GitHub/JaegerAI") == str(Path.home() / "GitHub/JaegerAI")
    for path in ("/etc", "/mnt/host/GitHub/../../.ssh", "/mnt/host/GitHub-other"):
        with pytest.raises(ValueError):
            host_workspace(path)


def test_openclaw_native_keeps_rest_session_key_and_filters_peer_events(tmp_path, monkeypatch):
    from jaeger_ai.interfaces.hermes_profile_adapters import openclaw_native as native
    run = Run(tmp_path, "existing-session", "hello")
    calls = []
    class Gateway:
        def __init__(self, *args):
            self.frames = iter([
                {"event": "exec.approval.requested", "payload": {"id": "wrong", "request": {"runId": "other", "sessionKey": "other"}}},
                {"event": "chat", "payload": {"runId": "other", "state": "delta", "deltaText": "WRONG"}},
                {"event": "agent", "payload": {"runId": run.id, "stream": "tool", "data": {"phase": "start", "name": "read", "toolCallId": "tool1"}}},
                {"event": "agent", "payload": {"runId": run.id, "stream": "tool", "data": {"phase": "result", "name": "read", "toolCallId": "tool1"}}},
                {"event": "chat", "payload": {"runId": run.id, "state": "delta", "deltaText": "Hello"}},
                {"event": "chat", "payload": {"runId": run.id, "state": "final", "message": {"content": [{"type": "text", "text": "Hello"}]}}},
            ])
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, method, params):
            calls.append((method, params))
            return {"runId": run.id}
        def next_event(self): return next(self.frames)
    monkeypatch.setattr(native, "NativeGateway", Gateway)
    assert native.openclaw_turn(run) == "Hello"
    assert run.output == "Hello"
    assert calls[0][1]["sessionKey"] == "agent:main:openai-user:hermes:existing-session"
    assert calls[0][1]["idempotencyKey"] == run.id
    assert not run.pending
    run.cancel()
    assert calls[-1] == ("chat.abort", {"sessionKey": "agent:main:openai-user:hermes:existing-session", "runId": run.id})


def test_openclaw_signs_native_challenge_without_changing_grants():
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from jaeger_ai.interfaces.hermes_profile_adapters.openclaw_native import connect_params, SCOPES
    key = Ed25519PrivateKey.generate()
    identity = {"deviceId": "test-device", "privateKeyPem": key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()}
    params = connect_params({"ts": 123, "nonce": "challenge"}, "fake-token", identity)
    encoded = params["device"]["signature"]
    signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    key.public_key().verify(signature, ("v3|test-device|cli|cli|operator|" + ",".join(SCOPES) + "|123|fake-token|challenge|linux|").encode())
    assert params["scopes"] == ["operator.read", "operator.write", "operator.approvals"]


def test_openclaw_fallback_streams_before_native_completion(monkeypatch):
    from io import BytesIO
    from jaeger_ai.interfaces.hermes_profile_adapters import openclaw
    released, entered = threading.Event(), threading.Event()
    requests = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"FIRST"}}]}\n'
            entered.set()
            released.wait(3)
            yield b'data: [DONE]\n'
    def request(req, **kwargs):
        requests.append(json.loads(req.data))
        return Response()
    monkeypatch.setattr(openclaw.urllib.request, "urlopen", request)
    monkeypatch.setattr(openclaw, "OPENCLAW_TOKEN_FILE", type("Token", (), {"read_text": lambda self: "fake"})())
    handler = object.__new__(openclaw.Handler)
    handler.wfile = BytesIO()
    handler.send_response = lambda *a: None
    handler.send_header = lambda *a: None
    handler.end_headers = lambda: None
    thread = threading.Thread(target=handler.stream_chat_completion, args=("current", "same-session"))
    thread.start()
    try:
        assert entered.wait(2)
        wait_for(lambda: b"FIRST" in handler.wfile.getvalue())
        assert thread.is_alive()
        assert requests[0]["stream"] is True
        assert requests[0]["user"] == "hermes:same-session"
    finally:
        released.set()
        thread.join(3)
    assert b"[DONE]" in handler.wfile.getvalue()


def test_openclaw_does_not_reinsert_native_history(monkeypatch):
    from io import BytesIO
    from jaeger_ai.interfaces.hermes_profile_adapters import openclaw
    calls = []
    handler = object.__new__(openclaw.Handler)
    body = json.dumps({"messages": [{"role": "user", "content": "OLD"},
        {"role": "assistant", "content": "ALREADY SAVED"}, {"role": "user", "content": "NEW"}]}).encode()
    handler.headers = {"Content-Length": str(len(body)), "X-Hermes-Session-Id": "same"}
    handler.rfile = BytesIO(body)
    handler.send_json = lambda *args: None
    monkeypatch.setattr(openclaw, "chat_openclaw", lambda *args: calls.append(args) or "OK")
    handler.create_chat_completion()
    assert calls == [("NEW", "same")]


def test_bridge_thread_ledger_switch_preserves_owner_not_other_session(tmp_path, monkeypatch):
    from jaeger_ai.core.runtime import work_ledger as ledger
    monkeypatch.setattr(ledger, "_layout_run_dir", lambda: tmp_path)
    ledger.reset()
    try:
        ledger.bind_session("table-one")
        result = ledger.work_ledger(action="create", task_name="Only table one", total_items=2, remaining_count=2)
        assert result["ok"]
        own = ledger.active_ledger()
        ledger.bind_session("unrelated-chat")
        assert ledger.active_ledger() is None
        assert ledger.context_block() == ""
        assert ledger.last_completion() is None
        ledger.bind_session("table-one")
        assert ledger.active_ledger().task_id == own.task_id
        assert "Only table one" in ledger.context_block()
        # Restore from disk, as after a native process restart.
        ledger._tls.session = None
        ledger._tls.active = None
        ledger._by_id.clear()
        ledger.bind_session("table-one")
        assert ledger.active_ledger().task_id == own.task_id
    finally:
        ledger.reset()


def test_background_turn_cannot_borrow_ui_sinks():
    from jaeger_ai.main import current_turn_sink, stream_delta_sink, stream_reasoning_sink, interaction_request_sink
    seen = []
    ready, release = threading.Event(), threading.Event()
    def other():
        seen.append(current_turn_sink("stream_delta_sink"))
        with stream_delta_sink(lambda x: seen.append(x)):
            ready.set()
            release.wait(2)
            current_turn_sink("stream_delta_sink")("other")
    mine = []
    with stream_delta_sink(mine.append), stream_reasoning_sink(mine.append), interaction_request_sink(mine.append):
        thread = threading.Thread(target=other)
        thread.start()
        try:
            assert ready.wait(2)
            current_turn_sink("stream_delta_sink")("mine")
            current_turn_sink("stream_reasoning_sink")("my progress")
        finally:
            release.set()
            thread.join(2)
    assert seen == [None, "other"]
    assert mine == ["mine", "my progress"]


def test_roundtable_smoke_does_not_accept_an_echoed_question():
    import runpy
    from pathlib import Path
    path = Path(__file__).resolve().parents[4] / "scripts/verify-agent-webui.py"
    check = runpy.run_path(str(path))["check_roundtable_answers"]
    with pytest.raises(RuntimeError):
        check("## Your Question\nRemember CHECKWORD\n## Round 1\n### Jaeger\n[Agent error: timed out]", "CHECKWORD", True)
    text = "\n".join(f"### {name}\nCHECKWORD\n" for name in ("Jaeger", "Hermes", "OpenClaw"))
    check(text, "CHECKWORD", True)


def test_native_cancel_selects_session_agent_not_global_background_pointer(monkeypatch):
    from types import SimpleNamespace
    from jaeger_ai import main
    interrupted = []
    own = SimpleNamespace(interrupt=lambda: interrupted.append("own"))
    other = SimpleNamespace(interrupt=lambda: interrupted.append("other"))
    event = threading.Event()
    monkeypatch.setattr(main, "_jaeger_agents_by_session", {"own": own, "other": other})
    monkeypatch.setitem(main._pipeline, "active_jaeger_agent", other)
    monkeypatch.setitem(main._pipeline, "current_session", "other")
    monkeypatch.setitem(main._pipeline, "cancel_event", event)
    main.request_turn_cancel(session_key="own")
    assert interrupted == ["own"]
    assert not event.is_set()
