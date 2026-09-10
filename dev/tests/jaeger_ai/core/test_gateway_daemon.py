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
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "jaeger-gateway"

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
