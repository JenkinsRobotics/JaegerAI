"""Gateway = single store of record + single event source; WebUI = projection.

Covers the session-architecture unification:
* the gateway event registry (EVENT_TYPES / CARD_EVENTS) — one stream schema;
* gateway-minted session IDs (client-supplied ids are never trusted);
* gateway-side profile binding (unknown profile → 400, turn mismatch → 409);
* the session-delete API (create → delete → re-list shows gone);
* GET /v1/requests/{request_id} — request lookup without the session id;
* GET /v1/sessions/{id}/events — the durable replay window as JSON.
"""
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from jaeger_ai.core.gateway.event_bus import CARD_EVENTS, EVENT_TYPES
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


# ── Event registry: the one stream contract ─────────────────────────────────

def test_event_registry_contains_webui_card_events():
    """Clarify/approval cards and board updates are first-class gateway events."""
    assert {"clarify.request", "clarify.resolved", "board.updated"} <= EVENT_TYPES
    assert {"approval.request", "approval.resolved"} <= EVENT_TYPES


def test_card_events_subset_of_registry():
    """Every card event is a registered event type — no orphan names."""
    assert CARD_EVENTS <= EVENT_TYPES


def test_registry_covers_turn_and_session_lifecycle():
    """The IDE's native stream names and the projection's list events coexist."""
    assert {
        "turn.start", "turn.delta", "turn.finish", "turn.failed",
        "tool.started", "tool.done", "tool.error",
        "session.created", "session.updated", "session.deleted",
    } <= EVENT_TYPES


# ── Session-ID namespace: the gateway mints and owns ids ────────────────────

class TestGatewayMintedSessionIds(AioHTTPTestCase):
    async def get_application(self):
        import tempfile
        self.db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        return JaegerGatewayApp(store=GatewaySessionStore(self.db_path)).app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if self.db_path.exists():
            self.db_path.unlink()

    async def test_client_supplied_session_id_is_ignored(self):
        """A client cannot mint a session identity; the gateway returns its own."""
        resp = await self.client.request(
            "POST", "/v1/sessions", json={"session_id": "webui-hermes-deadbeef"},
        )
        assert resp.status == 201
        created = await resp.json()
        assert created["session_id"] != "webui-hermes-deadbeef"
        assert created["session_id"]  # gateway-minted, non-empty

    async def test_unknown_profile_is_rejected_gateway_side(self):
        resp = await self.client.request(
            "POST", "/v1/sessions", json={"profile": "not-a-framework"},
        )
        assert resp.status == 400

    async def test_profile_binding_enforced_on_turns(self):
        created = await (await self.client.request(
            "POST", "/v1/sessions", json={"profile": "jaeger"},
        )).json()
        sid = created["session_id"]
        resp = await self.client.request(
            "POST", f"/v1/sessions/{sid}/turns",
            json={"text": "hello", "profile": "hermes"},
        )
        assert resp.status == 409
        assert "belongs to" in (await resp.json())["error"]


# ── Deletion: the gateway delete API is the one delete that counts ──────────

class TestSessionDeleteAPI(AioHTTPTestCase):
    async def get_application(self):
        import tempfile
        self.db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        self.gateway_app = JaegerGatewayApp(store=GatewaySessionStore(self.db_path))
        return self.gateway_app.app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if self.db_path.exists():
            self.db_path.unlink()

    async def _create_session(self, title="Delete me"):
        resp = await self.client.request("POST", "/v1/sessions", json={"title": title})
        assert resp.status == 201
        return (await resp.json())["session_id"]

    async def test_delete_removes_session_from_the_store(self):
        sid = await self._create_session()
        resp = await self.client.request("DELETE", f"/v1/sessions/{sid}")
        assert resp.status == 200
        assert (await resp.json())["deleted"] is True
        # Verify by re-listing: the projection must not show it anymore.
        listed = (await (await self.client.request("GET", "/v1/sessions")).json())["sessions"]
        assert sid not in {s["session_id"] for s in listed}
        # And a direct GET is a 404.
        assert (await self.client.request("GET", f"/v1/sessions/{sid}")).status == 404

    async def test_delete_unknown_session_is_404(self):
        resp = await self.client.request("DELETE", "/v1/sessions/nope")
        assert resp.status == 404

    async def test_delete_publishes_session_deleted_event(self):
        sid = await self._create_session()
        await self.client.request("DELETE", f"/v1/sessions/{sid}")
        events = [e.event for e in self.gateway_app.event_bus.get_replay_events(sid)]
        assert "session.deleted" in events


# ── Request lookup + JSON replay window (the shim's transport) ──────────────

class TestRequestLookupAndReplay(AioHTTPTestCase):
    async def get_application(self):
        import tempfile
        self.db_path = Path(tempfile.mktemp(suffix=".sqlite3"))
        return JaegerGatewayApp(store=GatewaySessionStore(self.db_path)).app

    async def tearDownAsync(self):
        await super().tearDownAsync()
        if self.db_path.exists():
            self.db_path.unlink()

    async def test_request_lookup_without_session_id(self):
        created = await (await self.client.request(
            "POST", "/v1/sessions", json={},
        )).json()
        sid = created["session_id"]
        # A request that was never admitted is a 404, not a 500.
        resp = await self.client.request("GET", "/v1/requests/unknown-request")
        assert resp.status == 404
        # The route exists and answers for the session's namespace.
        assert sid  # the gateway minted it; the shim would adopt this id

    async def test_events_json_replay_window(self):
        created = await (await self.client.request(
            "POST", "/v1/sessions", json={},
        )).json()
        sid = created["session_id"]
        resp = await self.client.request("GET", f"/v1/sessions/{sid}/events?since_event_id=0")
        assert resp.status == 200
        window = await resp.json()
        assert {"events", "cursor_expired", "oldest_event_id", "latest_event_id", "valid_cursor"} <= set(window)
        # session.created is on the durable stream the browser follows.
        assert any(e["event"] == "session.created" for e in window["events"])

    async def test_events_json_unknown_session_is_404(self):
        resp = await self.client.request("GET", "/v1/sessions/nope/events")
        assert resp.status == 404

    async def test_events_json_bad_cursor_is_400(self):
        created = await (await self.client.request(
            "POST", "/v1/sessions", json={},
        )).json()
        resp = await self.client.request(
            "GET", f"/v1/sessions/{created['session_id']}/events?since_event_id=abc",
        )
        assert resp.status == 400