"""Tests for Jaeger Gateway Daemon (Session Store, Event Bus, and Server)."""
import asyncio
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
        if hasattr(self, "db_path") and self.db_path.exists():
            self.db_path.unlink()
        await super().tearDownAsync()

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
        self.gateway_app._probe_webui_legacy_chat = _ok_webui  # type: ignore[method-assign]
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["all_green"] is True
        assert data["service"] == "jaeger-gateway"
        assert "webui_legacy_chat" in data["checks"]

    async def test_health_fail_closed_when_legacy_chat_500(self):
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
        self.gateway_app._probe_webui_legacy_chat = _chat_500  # type: ignore[method-assign]
        resp = await self.client.request("GET", "/health")
        assert resp.status == 503
        data = await resp.json()
        assert data["status"] == "unhealthy"
        assert data["all_green"] is False
        assert data["fail_closed"] is True
        assert data["checks"]["webui_legacy_chat"]["status_code"] == 500

    async def test_sessions_crud_and_turn(self):
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
        await asyncio.sleep(0.1)

        # 4. Fetch session history
        resp = await self.client.request("GET", "/v1/sessions/test-uuid")
        assert resp.status == 200
        sess_data = await resp.json()
        assert len(sess_data["messages"]) >= 2
        assert sess_data["messages"][0]["role"] == "user"
        assert sess_data["messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_native_lead_turn_success_and_soft_fail(monkeypatch):
    """Lead MCP path returns (text, mcp-label); failures soft-return None."""
    app = JaegerGatewayApp(store=GatewaySessionStore(Path("/tmp/gw-native-test.sqlite3")))

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def initialize(self):
            return {}

        def _execute_call(self, name, arguments):
            assert name in {"jaeger_chat", "chat"}
            assert arguments.get("session_id") == "dispatcher"
            return {"content": [{"type": "text", "text": "NATIVE_MCP_OK autonomy=tools"}]}

    import jaeger_ai.interfaces.hermes_profile_adapters.jaeger as jaeger_mcp

    monkeypatch.setattr(jaeger_mcp, "MCPClient", _FakeClient)
    monkeypatch.setattr(jaeger_mcp, "MCP_GATEWAY_URL", "http://127.0.0.1:8811/mcp")
    monkeypatch.setattr(jaeger_mcp, "MCP_API_KEY", "")
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

    async def _fake_native(session_id, text):
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
