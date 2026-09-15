"""Tests for Jaeger Gateway Daemon (Session Store, Event Bus, and Server)."""
import asyncio
import json
import os
import pytest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from pathlib import Path

from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.server import JaegerGatewayApp


def test_session_store_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_sessions.sqlite3"
    store = GatewaySessionStore(db_file)

    # 1. Ensure new session
    session = store.ensure_session("sess-1", title="First Task", profile="jaeger")
    assert session["session_id"] == "sess-1"
    assert session["title"] == "First Task"
    assert session["profile"] == "jaeger"
    assert session["status"] == "idle"

    # 2. Append messages
    msg1_id = store.append_message("sess-1", "user", "Please check my code")
    msg2_id = store.append_message(
        "sess-1",
        "assistant",
        "Looking into it now",
        tool_calls=[{"name": "read_file", "args": {"path": "main.py"}}],
    )
    assert msg1_id > 0
    assert msg2_id > msg1_id

    # 3. Retrieve session with transcript
    fetched = store.get_session("sess-1")
    assert fetched is not None
    assert len(fetched["messages"]) == 2
    assert fetched["messages"][0]["role"] == "user"
    assert fetched["messages"][1]["role"] == "assistant"
    assert fetched["messages"][1]["tool_calls"][0]["name"] == "read_file"

    # 4. List sessions
    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["message_count"] == 2

    # 5. Delete session
    assert store.delete_session("sess-1") is True
    assert store.get_session("sess-1") is None
    assert len(store.list_sessions()) == 0


def test_event_bus_pub_sub_and_replay():
    bus = GatewayEventBus(ring_buffer_size=10)

    # Publish 3 events
    e1 = bus.publish("sess-A", "turn.start", {"turn": 1})
    e2 = bus.publish("sess-A", "turn.delta", {"text": "hello"})
    e3 = bus.publish("sess-B", "turn.start", {"turn": 1})
    assert e1.event_id == 1
    assert e2.event_id == 2
    assert e3.event_id == 3

    # Test replay for sess-A since event 1
    replay = bus.get_replay_events("sess-A", since_event_id=1)
    assert len(replay) == 1
    assert replay[0].event_id == 2
    assert replay[0].event == "turn.delta"


class TestGatewayServerAPI(AioHTTPTestCase):
    async def get_application(self):
        import tempfile
        self.db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        self.temp_store = GatewaySessionStore(self.db_path)
        self.gateway_app = JaegerGatewayApp(store=self.temp_store)
        return self.gateway_app.app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if hasattr(self, "db_path") and self.db_path.exists():
            self.db_path.unlink()

    async def test_health_check(self):
        # Hermetic: stub dependency probes so unit test does not hit live LAN.
        async def _ok_http(url, *, timeout_s: float = 2.0):
            return {"ok": True, "status_code": 200, "url": url}

        async def _ok_webui(*, timeout_s: float = 3.0):
            return {
                "ok": True,
                "status_code": 404,
                "url": "http://test/api/chat",
                "required": True,
                "note": "legacy /api/chat reachable (non-500)",
            }

        self.gateway_app._probe_http = _ok_http  # type: ignore[method-assign]
        self.gateway_app._probe_native_mcp = _ok_webui
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["all_green"] is True
        assert data["service"] == "jaeger-gateway"
        assert "native_mcp" in data["checks"]
        assert data["capabilities"]["end_to_end_chat_verified"] is False

    async def test_version_contract_is_semver_and_side_effect_free(self):
        resp = await self.client.request("GET", "/version")
        assert resp.status == 200
        data = await resp.json()
        assert data["component"] == "jaeger-gateway"
        assert data["version"].count(".") == 2
        assert data["version"].replace(".", "").isdigit()
        assert data["protocol_version"] == "1"

    async def test_health_fail_closed_when_native_mcp_unavailable(self):
        async def _ok_http(url, *, timeout_s: float = 2.0):
            return {"ok": True, "status_code": 200, "url": url}

        async def _chat_500(*, timeout_s: float = 3.0):
            return {
                "ok": False,
                "status_code": 500,
                "url": "http://test/api/chat",
                "required": True,
                "note": "legacy /api/chat returned 500",
            }

        self.gateway_app._probe_http = _ok_http  # type: ignore[method-assign]
        self.gateway_app._probe_native_mcp = _chat_500
        resp = await self.client.request("GET", "/health")
        assert resp.status == 503
        data = await resp.json()
        assert data["status"] == "unhealthy"
        assert data["all_green"] is False
        assert data["fail_closed"] is True
        assert data["checks"]["native_mcp"]["ok"] is False

    async def test_sessions_crud_and_turn(self):
        finished = asyncio.Event()
        async def native(session_id, text, **kwargs):
            finished.set()
            return "Audit response", "mcp:test"
        self.gateway_app._native_lead_turn = native
        # 1. Create session
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={"session_id": "test-uuid", "title": "Audit Task", "profile": "roundtable"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["session_id"] == "test-uuid"
        assert data["profile"] == "roundtable"

        # 2. List sessions
        resp = await self.client.request("GET", "/v1/sessions")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["sessions"]) == 1

        # 3. Post turn
        resp = await self.client.request(
            "POST",
            "/v1/sessions/test-uuid/turns",
            json={"text": "Audit security posture"},
        )
        assert resp.status == 200
        turn_data = await resp.json()
        assert turn_data["session_id"] == "test-uuid"
        assert turn_data["status"] == "running"

        # Wait for background turn execution
        await asyncio.wait_for(finished.wait(), timeout=2)

        # 4. Fetch session history
        resp = await self.client.request("GET", "/v1/sessions/test-uuid")
        assert resp.status == 200
        sess_data = await resp.json()
        assert len(sess_data["messages"]) >= 2
        assert sess_data["messages"][0]["role"] == "user"
        assert sess_data["messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_native_lead_turn_success_and_soft_fail(monkeypatch, tmp_path):
    """Lead MCP path returns (text, mcp-label); failures soft-return None."""
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "native.sqlite3"))

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            return {}

        def list_tools(self):
            return [{"name": "jaeger_chat"}]

        def _execute_call(self, name, arguments):
            assert name in {"jaeger_chat", "chat"}
            assert arguments.get("session_id") == "dispatcher"
            return {"content": [{"type": "text", "text": "NATIVE_MCP_OK autonomy=tools"}]}

    import jaeger_ai.core.frameworks.jaeger as jaeger_mcp

    monkeypatch.setattr(jaeger_mcp, "MCPClient", _FakeClient)
    monkeypatch.setattr(jaeger_mcp, "MCP_GATEWAY_URL", "http://127.0.0.1:8811/mcp")
    monkeypatch.setattr(jaeger_mcp, "mcp_api_key", lambda: "")
    monkeypatch.setattr(jaeger_mcp, "MCP_HOST_HEADER", "127.0.0.1:8811")

    ok = await app._native_lead_turn("sess-native", "What is your autonomy mode?")
    assert ok is not None
    text, label = ok
    assert "NATIVE_MCP_OK" in text
    assert label.startswith("mcp")

    class _BoomClient:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            raise RuntimeError("mcp down")

        def _execute_call(self, name, arguments):
            raise RuntimeError("mcp down")

    monkeypatch.setattr(jaeger_mcp, "MCPClient", _BoomClient)
    failed = await app._native_lead_turn("sess-native", "hello")
    assert failed is None


@pytest.mark.asyncio
async def test_execute_turn_lead_uses_mcp_backend(monkeypatch, tmp_path):
    """Non-specialist turns stamp turn.finish backend from native MCP label."""
    store = GatewaySessionStore(tmp_path / "native_turn.sqlite3")
    bus = GatewayEventBus()
    app = JaegerGatewayApp(store=store, event_bus=bus)
    store.ensure_session("s1", title="native", profile="jaeger")

    async def _fake_native(session_id, text, **kwargs):
        return ("lead via mcp with tools", "mcp:127.0.0.1:8811")

    async def _should_not_ollama(*a, **k):
        raise AssertionError("ollama should not run when MCP succeeds")

    monkeypatch.setattr(app, "_native_lead_turn", _fake_native)
    monkeypatch.setattr(app, "_ollama_chat", _should_not_ollama)
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)

    await app._execute_turn("s1", "turn-1", "Describe autonomy mode briefly.")
    sess = store.get_session("s1")
    assert sess["status"] == "idle"
    assert any("lead via mcp" in m["content"] for m in sess["messages"] if m["role"] == "assistant")
    finishes = [e for e in bus.get_replay_events("s1", since_event_id=0) if e.event == "turn.finish"]
    assert finishes
    assert finishes[-1].data["backend"].startswith("mcp")


@pytest.mark.asyncio
async def test_execute_turn_specialist_skips_mcp(monkeypatch, tmp_path):
    store = GatewaySessionStore(tmp_path / "spec_turn.sqlite3")
    bus = GatewayEventBus()
    app = JaegerGatewayApp(store=store, event_bus=bus)
    store.ensure_session("s2", title="spec", profile="jaeger")

    class _Agent:
        id = "agent-spec"
        display_name = "Ops"
        role = type("R", (), {"value": "specialist"})()
        metadata = {"specialty": "ops"}

    async def _boom_native(*a, **k):
        raise AssertionError("specialist must not call native MCP")

    async def _ollama(text, *, system_prompt=None):
        assert "specialist" in (system_prompt or "").lower()
        return "SPECIALIST:Ops"

    monkeypatch.setattr(app, "_native_lead_turn", _boom_native)
    monkeypatch.setattr(app, "_ollama_chat", _ollama)
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: _Agent())

    await app._execute_turn("s2", "turn-2", "name?")
    finishes = [e for e in bus.get_replay_events("s2", since_event_id=0) if e.event == "turn.finish"]
    assert finishes[-1].data["backend"]  # locked ollama url
    assert "mcp" not in str(finishes[-1].data["backend"])


@pytest.mark.asyncio
async def test_native_failure_does_not_silently_complete_with_text(monkeypatch, tmp_path):
    store = GatewaySessionStore(tmp_path / "failure.sqlite3")
    app = JaegerGatewayApp(store=store)
    store.ensure_session("s")
    async def unavailable(*args, **kwargs):
        return None
    async def forbidden(*args, **kwargs):
        raise AssertionError("implicit text fallback")
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    monkeypatch.setattr(app, "_native_lead_turn", unavailable)
    monkeypatch.setattr(app, "_ollama_chat", forbidden)
    await app._execute_turn("s", "t", "Remember this")
    assert store.get_session("s")["status"] == "failed"
    events = app.event_bus.get_replay_events("s", since_event_id=0)
    assert [e.event for e in events] == ["turn.failed"]
    assert "did not return a confirmed result" in events[0].data["error"]


@pytest.mark.asyncio
async def test_explicit_text_mode_reports_missing_native_capabilities(monkeypatch, tmp_path):
    store = GatewaySessionStore(tmp_path / "text.sqlite3")
    app = JaegerGatewayApp(store=store)
    store.ensure_session("s", metadata={"execution_mode": "text_only"})
    async def unavailable(*args, **kwargs):
        raise AssertionError("Explicit text mode must not execute native work")
    async def text(*args, **kwargs):
        return "Text response"
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    monkeypatch.setattr(app, "_native_lead_turn", unavailable)
    monkeypatch.setattr(app, "_ollama_chat", text)
    await app._execute_turn("s", "t", "hello")
    finish = app.event_bus.get_replay_events("s", since_event_id=0)[-1]
    assert finish.event == "turn.finish"
    assert finish.data["execution_mode"] == "text_only"
    assert finish.data["capabilities"] == {"native_tools": False, "native_memory": False}


@pytest.mark.asyncio
async def test_text_only_model_must_be_explicit(monkeypatch, tmp_path):
    import jaeger_ai.core.gateway.server as gateway

    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "text-model.sqlite3"))
    monkeypatch.setattr(gateway, "DEFAULT_OLLAMA_MODEL", "")
    with pytest.raises(RuntimeError, match="JAEGER_GATEWAY_OLLAMA_MODEL"):
        await app._ollama_chat("hello")


@pytest.mark.asyncio
async def test_mcp_health_requires_chat_catalog_not_merely_http_200(monkeypatch, tmp_path):
    from aiohttp import web
    from aiohttp.test_utils import TestServer
    import jaeger_ai.core.frameworks.jaeger as transport
    methods = []
    catalog = []
    async def handler(request):
        body = await request.json()
        methods.append(body["method"])
        if body["method"] == "notifications/initialized":
            return web.Response(status=202)
        result = {"tools": catalog} if body["method"] == "tools/list" else {"capabilities": {}}
        if body["method"] == "tools/call":
            assert body["params"]["name"] == "bridge_health"
            result = {"structuredContent": {"ok": True, "ready": {"agent": "ready"}}}
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": result})
    service = web.Application()
    service.router.add_post("/mcp", handler)
    async with TestServer(service) as server:
        monkeypatch.setattr(transport, "MCP_GATEWAY_URL", str(server.make_url("/mcp")))
        app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "health.sqlite3"))
        assert (await app._probe_native_mcp())["ok"] is False
        catalog.append({"name": "chat"})
        assert (await app._probe_native_mcp())["ok"] is False
        catalog.append({"name": "bridge_health"})
        assert (await app._probe_native_mcp())["ok"] is True
    assert methods.count("tools/call") == 1


@pytest.mark.asyncio
async def test_native_uncertain_result_is_not_reexecuted_under_another_tool(monkeypatch, tmp_path):
    import jaeger_ai.core.frameworks.jaeger as transport
    calls = []
    class Client:
        def __init__(self, *args): pass
        def initialize(self): return {}
        def list_tools(self): return [{'name': 'jaeger_chat'}, {'name': 'chat'}]
        def _execute_call(self, name, arguments):
            calls.append(name)
            raise TimeoutError('Response lost after acceptance')
    monkeypatch.setattr(transport, 'MCPClient', Client)
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'uncertain.sqlite3'))
    assert await app._native_lead_turn('s', 'perform work') is None
    assert calls == ['jaeger_chat']


def test_mcp_tool_discovery_follows_catalog_without_calling_tools(monkeypatch):
    import io
    import json
    import jaeger_ai.core.frameworks.jaeger as transport
    seen = []
    def respond(request, **kwargs):
        body = json.loads(request.data)
        seen.append(body)
        assert body['method'] == 'tools/list'
        result = ({'tools': [{'name': 'other'}], 'nextCursor': 'next'} if len(seen) == 1
                  else {'tools': [{'name': 'jaeger_chat'}]})
        return io.BytesIO(json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result}).encode())
    monkeypatch.setattr(transport.urllib.request, 'urlopen', respond)
    client = transport.MCPClient('http://127.0.0.1:8811/mcp', '', '127.0.0.1:8811')
    assert [t['name'] for t in client.list_tools()] == ['other', 'jaeger_chat']
    assert seen[1]['params']['cursor'] == 'next'


@pytest.mark.asyncio
async def test_backend_health_does_not_require_ui_or_http_adapter(monkeypatch, tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'backend.sqlite3'))
    async def http(url, **kwargs):
        return {'ok': url.endswith('/api/tags'), 'url': url}
    async def native(**kwargs):
        return {'ok': True, 'agent_ready': True, 'chat_tool_available': True}
    monkeypatch.setattr(app, '_probe_http', http)
    monkeypatch.setattr(app, '_probe_native_mcp', native)
    response = await app.handle_health(None)
    import json
    body = json.loads(response.body)
    assert response.status == 200
    assert body['all_green'] is True
    assert body['checks']['webui']['ok'] is False
    assert body['checks']['webui']['required'] is False
    assert body['checks']['bridge']['required'] is False
    assert body['health_scope'] == 'backend_transport_readiness'


@pytest.mark.asyncio
async def test_gateway_restart_preserves_transcript_and_marks_unconfirmed_work(tmp_path):
    path = tmp_path / 'restart.sqlite3'
    store = GatewaySessionStore(path)
    store.ensure_session('inflight')
    store.append_message('inflight', 'user', 'accepted before restart')
    store.update_status('inflight', 'running')
    restarted = JaegerGatewayApp(store=GatewaySessionStore(path))
    assert restarted.store.get_session('inflight')['status'] == 'running'
    await restarted._recover_interrupted(restarted.app)
    recovered = restarted.store.get_session('inflight')
    assert recovered['status'] == 'execution_unknown'
    assert recovered['messages'][0]['content'] == 'accepted before restart'
    assert len(recovered['messages']) == 1
    assert restarted.store.recover_interrupted_sessions() == 0


def test_admit_request_is_atomic_and_conflicts_on_fingerprint(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "admit.sqlite3")
    first = store.admit_request("s", "same work", request_id="a" * 32)
    assert first["accepted"] is True
    replay = store.admit_request("s", "same work", request_id="a" * 32)
    assert replay["replayed"] is True
    assert replay["turn_id"] == first["turn_id"]
    from jaeger_ai.core.gateway.session_store import RequestBusy, RequestConflict
    with pytest.raises(RequestConflict, match="different input"):
        store.admit_request("s", "other work", request_id="a" * 32)
    with pytest.raises(RequestBusy):
        store.admit_request("s", "second turn", request_id="b" * 32)
    store.complete_request(first["request_id"], status="completed", result={"output": "done"}, assistant_text="done")
    again = store.admit_request("s", "same work", request_id="a" * 32)
    assert again["result"]["output"] == "done"


def test_process_lease_and_backup_preserve_sessions(tmp_path: Path):
    src = tmp_path / "live.sqlite3"
    store = GatewaySessionStore(src)
    store.ensure_session("keep", title="Keep me")
    store.append_message("keep", "user", "hello")
    claimed = store.claim_process(pid=os.getpid(), source_file="test")
    assert claimed["ok"] is True
    foreign = store.claim_process(pid=os.getpid() + 99999, source_file="other")
    # The existing owner is alive, so a different claimant cannot steal it.
    assert foreign["ok"] is False
    dest = tmp_path / "backup.sqlite3"
    store.backup(dest)
    restored = GatewaySessionStore(dest)
    assert restored.schema_version() == store.schema_version()
    session = restored.get_session("keep")
    assert session["messages"][0]["content"] == "hello"


def test_durable_events_and_expired_cursor(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "events.sqlite3")
    store.ensure_session("s")
    first = store.append_event("s", "turn.start", {"n": 1})
    store.append_event("s", "turn.finish", {"n": 2})
    replay = store.replay_events("s", first["event_id"] - 1)
    assert replay["valid_cursor"] is True
    assert [e["event"] for e in replay["events"]] == ["turn.start", "turn.finish"]
    expired = store.replay_events("s", 0)
    assert expired["cursor_expired"] is False


def test_approval_first_writer_wins_and_deny_is_terminal(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "appr.sqlite3")
    created = store.create_approval(kind="tool", prompt="Allow write?", options=["once", "deny"])
    first = store.resolve_approval(created["approval_id"], approved=False, decision="deny")
    assert first["decision"] == "deny"
    assert store.resolve_approval(created["approval_id"], approved=True) is None


@pytest.mark.asyncio
async def test_duplicate_turn_submission_executes_once(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "once.sqlite3")
    app = JaegerGatewayApp(store=store)
    calls = []

    async def native(session_id, text, **kwargs):
        calls.append(text)
        await asyncio.sleep(0.05)
        return "ONCE", "mcp:test"

    app._native_lead_turn = native  # type: ignore[method-assign]
    body = {"text": "do the thing", "request_id": "c" * 32}

    class Req:
        def __init__(self):
            self.match_info = {"id": "sess"}
            self.can_read_body = True
        async def json(self):
            return body

    first, second = await asyncio.gather(app.handle_send_turn(Req()), app.handle_send_turn(Req()))
    assert first.status == 200
    assert second.status == 200
    one = json.loads(first.body)
    two = json.loads(second.body)
    assert one["turn_id"] == two["turn_id"]
    await asyncio.wait_for(asyncio.sleep(0), timeout=1)
    task = app._running_tasks.get("c" * 32)
    if task:
        await asyncio.wait_for(task, timeout=2)
    assert calls == ["do the thing"]
    session = store.get_session("sess")
    assert sum(1 for m in session["messages"] if m["role"] == "user") == 1


@pytest.mark.asyncio
async def test_cancel_before_native_prevents_effect(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "cancel.sqlite3")
    app = JaegerGatewayApp(store=store)
    release = asyncio.Event()
    called = []

    async def native(session_id, text, **kwargs):
        called.append(text)
        await release.wait()
        return "should not matter", "mcp:test"

    app._native_lead_turn = native  # type: ignore[method-assign]
    admitted = store.admit_request("s", "work", request_id="d" * 32)
    app._cancel_requested.add(admitted["request_id"])
    await app._execute_turn("s", admitted["turn_id"], "work", request_id=admitted["request_id"])
    release.set()
    assert called == []
    assert store.get_request(admitted["request_id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reconcile_uses_native_receipt_and_does_not_replay(tmp_path: Path, monkeypatch):
    store = GatewaySessionStore(tmp_path / "recon.sqlite3")
    app = JaegerGatewayApp(store=store)
    admitted = store.admit_request("s", "work", request_id="e" * 32)
    store.bind_native(admitted["request_id"], native_run_id="e" * 32, native_session="dispatcher")
    store.mark_request_status(admitted["request_id"], "execution_unknown")
    store.update_status("s", "execution_unknown")
    monkeypatch.setattr(app, "_native_receipt", lambda *a, **k: {
        "turn_id": "e" * 32, "session_id": "dispatcher", "status": "completed",
        "execution_unknown": False, "reply": {"text": "from native"},
    })

    class Req:
        match_info = {"id": "s"}
        can_read_body = True
        async def json(self):
            return {"request_id": "e" * 32}

    resp = await app.handle_reconcile(Req())
    body = json.loads(resp.body)
    assert resp.status == 200
    assert body["reconciled"] is True
    assert body["status"] == "completed"
    assert "from native" in store.get_session("s")["messages"][-1]["content"]
    replay = store.admit_request("s", "work", request_id="e" * 32)
    assert replay["replayed"] is True
    assert replay["status"] == "completed"


class _FakeAgent:
    def __init__(self, agent_id, display_name, specialty):
        self.id = agent_id
        self.display_name = display_name
        self.metadata = {"role": specialty, "specialty": specialty}


class _FakeRegistry:
    def __init__(self, agents):
        self._agents = {a.id: a for a in agents}

    def get_agent(self, agent_id):
        return self._agents.get(agent_id)


@pytest.mark.asyncio
async def test_specialist_handoff_executes_isolated_child(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    store = GatewaySessionStore(tmp_path / "ho.sqlite3")
    app = JaegerGatewayApp(store=store)
    app._registry = lambda: _FakeRegistry([_FakeAgent("native:everyday", "Everyday", "everyday")])
    seen = []

    async def specialist(session_id, text, *, request_id, allowed_tools):
        seen.append(session_id)
        assert request_id == "f" * 32
        assert allowed_tools == []
        assert "dispatcher" not in session_id
        assert "SECRET_PRIVATE" not in text
        return "child-result", "mcp:specialist"

    app._specialist_chat = specialist  # type: ignore[method-assign]

    class Create:
        match_info = {"id": "native:everyday"}
        can_read_body = True
        async def json(self):
            return {
                "task": "Reply with the calendar hint",
                "require_approval": False,
                "from_agent_id": "native:jaeger",
                "request_id": "f" * 32,
                "permitted_context": "calendar is free at 3pm",
                "timeout_seconds": 5,
            }

    created = await app.handle_handoff_agent(Create())
    body = json.loads(created.body)
    assert created.status == 200
    task = app._running_tasks.get("f" * 32)
    if task:
        await asyncio.wait_for(task, timeout=2)
    final = store.get_handoff(body["id"])
    assert final["status"] == "completed"
    assert final["result"]["ok"] is True
    assert "child-result" in final["result"]["summary"]
    assert seen and seen[0].startswith("specialist:")


@pytest.mark.asyncio
async def test_denied_handoff_does_not_execute(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    store = GatewaySessionStore(tmp_path / "deny.sqlite3")
    app = JaegerGatewayApp(store=store)
    app._registry = lambda: _FakeRegistry([_FakeAgent("native:surfaces", "Surfaces", "surfaces")])
    called = []

    async def specialist(session_id, text, **kwargs):
        called.append(text)
        return "nope", "mcp"

    app._specialist_chat = specialist  # type: ignore[method-assign]

    class Create:
        match_info = {"id": "native:surfaces"}
        can_read_body = True
        async def json(self):
            return {"task": "change chrome", "require_approval": True, "from_agent_id": "native:jaeger"}

    created = await app.handle_handoff_agent(Create())
    handoff = json.loads(created.body)

    class Decide:
        match_info = {"id": handoff["approval_id"]}
        can_read_body = True
        async def json(self):
            return {"approved": False}

    resolved = await app.handle_resolve_approval(Decide())
    assert json.loads(resolved.body)["approved"] is False
    await asyncio.sleep(0.05)
    assert called == []
    assert store.get_handoff(handoff["id"])["status"] == "denied"


@pytest.mark.asyncio
async def test_recursive_delegation_is_rejected(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    store = GatewaySessionStore(tmp_path / "loop.sqlite3")
    app = JaegerGatewayApp(store=store)
    app._registry = lambda: _FakeRegistry([_FakeAgent("native:gateway", "Gateway", "gateway")])

    class Create:
        match_info = {"id": "native:gateway"}
        can_read_body = True
        async def json(self):
            return {
                "task": "loop",
                "require_approval": False,
                "from_agent_id": "native:jaeger",
                "parent_chain": ["native:jaeger", "native:gateway"],
            }

    resp = await app.handle_handoff_agent(Create())
    assert resp.status == 409
    assert "loop" in json.loads(resp.body)["error"]


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_accepted_work(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "disc.sqlite3")
    bus = GatewayEventBus(store=store)
    app = JaegerGatewayApp(store=store, event_bus=bus)
    release = asyncio.Event()

    async def native(session_id, text, **kwargs):
        await release.wait()
        return "still running", "mcp:test"

    app._native_lead_turn = native  # type: ignore[method-assign]
    req_body = {"text": "keep going", "request_id": "1" * 32}

    class Req:
        match_info = {"id": "s"}
        can_read_body = True
        async def json(self):
            return req_body

    accepted = await app.handle_send_turn(Req())
    assert json.loads(accepted.body)["status"] == "running"
    # Dropping a subscriber is not a cancel.
    assert store.get_request("1" * 32)["status"] in {"admitted", "running"}
    release.set()
    task = app._running_tasks.get("1" * 32)
    if task:
        await asyncio.wait_for(task, timeout=2)
    assert store.get_request("1" * 32)["status"] == "completed"
