"""One unknown-outcome turn must never lock a conversation, and nothing is replayed (2026-10-21)."""
import tempfile
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _stranded(store: GatewaySessionStore, sid: str = "s") -> dict:
    """A turn whose stream was killed mid-effect: request + session left execution_unknown."""
    first = store.admit_request(sid, "run the long tool", request_id="r1")
    store.complete_request("r1", status="execution_unknown",
                           result={"status": "execution_unknown", "output": None,
                                   "error": "cancelled with an external effect whose outcome is unknown; reconcile"},
                           session_status="execution_unknown")
    assert store.get_session(sid)["status"] == "execution_unknown"
    return first


def test_next_send_after_a_killed_turn_is_admitted_and_nothing_is_replayed(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    seen = []
    store.event_sink = seen.append
    _stranded(store)
    nxt = store.admit_request("s", "hello again", request_id="r2")
    assert nxt["accepted"] is not False and nxt["request_id"] == "r2"
    assert nxt["acknowledged_unknown"] == ["r1"]
    old = store.get_request("r1")
    assert old["status"] == "execution_unknown"                    # truth kept
    assert old["result"]["acknowledged"]["replayed"] is False      # never replayed
    assert [e["event"] for e in seen] == ["turn.unknown.acknowledged"]
    # The same r1 identity cannot be resubmitted as a new execution.
    again = store.admit_request("s", "run the long tool", request_id="r1")
    assert again["replayed"] is True and again["accepted"] is False


def test_owner_acknowledgement_is_idempotent_and_frees_the_session(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    _stranded(store)
    assert len(store.acknowledge_unknown("s", actor="owner:cli", request_id="r1")) == 1
    assert store.acknowledge_unknown("s", actor="owner:cli", request_id="r1") == []
    assert store.get_session("s")["status"] == "idle"


def test_running_turn_still_blocks_a_second_turn(tmp_path: Path):
    import pytest
    from jaeger_ai.core.gateway.session_store import RequestBusy
    store = GatewaySessionStore(tmp_path / "s.sqlite3")
    store.admit_request("s", "first", request_id="r1")
    with pytest.raises(RequestBusy):
        store.admit_request("s", "second", request_id="r2")


class TestReconcileAcknowledge(AioHTTPTestCase):
    async def get_application(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.gw = JaegerGatewayApp(store=GatewaySessionStore(self.tmp / "s.sqlite3"))
        return self.gw.app

    async def test_reconcile_without_receipt_can_be_acknowledged_by_the_owner(self):
        _stranded(self.gw.store, "sess")
        h = client_headers("cli")
        r = await self.client.request("POST", "/v1/sessions/sess/reconcile", json={"request_id": "r1"}, headers=h)
        assert r.status == 409 and (await r.json())["execution_unknown"] is True   # still unknown, not replayed
        r = await self.client.request("POST", "/v1/sessions/sess/reconcile",
                                      json={"request_id": "r1", "acknowledge_unknown": True}, headers=h)
        body = await r.json()
        assert r.status == 200 and body["outcome"] == "unknown_not_replayed" and body["status"] == "execution_unknown"
        assert body["result"]["acknowledged"]["by"] == "owner:cli"
        assert self.gw.store.get_session("sess")["status"] == "idle"
        events = [e.event for e in self.gw.event_bus.get_replay_events("sess")]
        assert "turn.unknown.acknowledged" in events
