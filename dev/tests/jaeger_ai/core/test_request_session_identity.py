"""Request identities stay bound to their original conversation. No provider execution."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.caller_auth import (
    CALLERS,
    prefixed_route_allowed,
    session_allowed,
)
from jaeger_ai.core.gateway.server import _REQUEST_CALLER, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import (
    GatewaySessionStore,
    RequestConflict,
    input_fingerprint,
)

CHOICES = {
    "caller": "owner:cli",
    "interaction_tier": "agent",
    "allowed_tools": ["filesystem.read"],
}


@pytest.fixture
def store(tmp_path):
    store = GatewaySessionStore(tmp_path / "sessions.sqlite3")
    receipt = store.admit_request(
        "private-chat", "Summarize this", request_id="known-id", requested=CHOICES
    )
    store.complete_request(
        receipt["request_id"],
        status="completed",
        result={"output": "PRIVATE ANSWER"},
        assistant_text="PRIVATE ANSWER",
    )
    return store


def test_same_session_replay(store):
    old = store.get_request("known-id")
    replay = store.admit_request(
        "private-chat", "Summarize this", request_id="known-id", requested=CHOICES
    )
    assert replay["replayed"] and replay["turn_id"] == old["turn_id"]
    assert replay["result"]["output"] == "PRIVATE ANSWER"


@pytest.mark.parametrize(
    "changes",
    [{"text": "different"}, {"caller": "mcp"}, {"allowed_tools": ["terminal.run"]}],
)
def test_changed_identity_conflicts(store, changes):
    choices = {**CHOICES, **{k: v for k, v in changes.items() if k != "text"}}
    with pytest.raises(RequestConflict):
        store.admit_request(
            "private-chat",
            changes.get("text", "Summarize this"),
            request_id="known-id",
            requested=choices,
        )


def test_other_session_rejected_before_guard_or_creation(store):
    guards = []
    with pytest.raises(RequestConflict):
        store.admit_request(
            "unrelated-new-chat",
            "Summarize this",
            request_id="known-id",
            requested=CHOICES,
            admission_guard=lambda conn: guards.append(True),
        )
    assert not guards
    assert store.get_session("unrelated-new-chat") is None


class Req(dict):
    can_read_body = True

    def __init__(self, sid, caller, **changes):
        super().__init__(caller=CALLERS[caller], caller_actor=CALLERS[caller].actor)
        self.match_info = {"id": sid}
        self.body = {
            "text": "Summarize this",
            "request_id": "known-id",
            "allowed_tools": ["filesystem.read"],
            **changes,
        }

    async def json(self):
        return self.body


def handler(store, sid, caller="cli", **changes):
    # Actual normalization, model validation, admission, owner activation and response.
    # Only event publication/current-tier lookup stubbed. Completed replay cannot execute.
    app = JaegerGatewayApp.__new__(JaegerGatewayApp)
    app.store = store
    app.event_bus = SimpleNamespace(publish=lambda *a, **kw: None)
    app._current_tier = lambda: "agent"
    app._running_tasks = {}
    token = _REQUEST_CALLER.set((caller, CALLERS[caller].actor))
    try:
        response = asyncio.run(app.handle_send_turn(Req(sid, caller, **changes)))
    finally:
        _REQUEST_CALLER.reset(token)
    return response.status, json.loads(response.body)


def test_handler_same_session_control(store):
    status, body = handler(store, "private-chat")
    assert status == 200 and body["output"] == "PRIVATE ANSWER" and body["replayed"]


@pytest.mark.parametrize(
    "changes", [{"text": "different"}, {"allowed_tools": ["terminal.run"]}]
)
def test_handler_changed_identity_control(store, changes):
    assert handler(store, "other-chat", **changes)[0] == 409
    assert store.get_session("other-chat") is None


def test_handler_authenticated_caller_conflicts(store):
    assert handler(store, "mcp:destination", "mcp")[0] == 409
    assert store.get_session("mcp:destination") is None


def test_handler_wrong_session_rejects_without_activation(store):
    status, body = handler(store, "other-chat")
    assert status == 409, body
    assert store.get_session("other-chat") is None
    assert store.active_session_state().get("active_session_id") is None


def test_legacy_receipt_cannot_cross_caller_prefix(store):
    # Supported migrated v1 receipts have text-only digest and empty execution.
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE client_requests SET digest_version=1,digest=?,execution_json='{}' WHERE request_id='known-id'",
            (input_fingerprint("Summarize this"),),
        )
    spec = CALLERS["mcp"]
    assert not session_allowed(spec, "private-chat")
    assert session_allowed(spec, "mcp:destination")
    assert prefixed_route_allowed("POST", "/v1/sessions/{id}/turns", "mcp")
    status, body = handler(store, "mcp:destination", "mcp")
    assert status == 409, body
    assert store.get_session("mcp:destination") is None


def test_enqueue_cannot_replay_foreign_session_receipt(store):
    with pytest.raises(RequestConflict):
        store.enqueue_request(
            "queue-other", "Summarize this", request_id="known-id", requested=CHOICES
        )
    assert store.get_session("queue-other") is None


@pytest.mark.parametrize("method", ["admit_request", "enqueue_request"])
@pytest.mark.parametrize("legacy", [False, True])
def test_foreign_identity_preserves_existing_destination(store, method, legacy):
    store.ensure_session("destination", title="Keep me")
    store.update_metadata("destination", {"model": "unchanged"})
    before = store.get_session("destination")
    if legacy:
        with sqlite3.connect(store.path) as conn:
            conn.execute(
                "UPDATE client_requests SET digest_version=1,digest=?,execution_json='{}' WHERE request_id='known-id'",
                (input_fingerprint("Summarize this"),),
            )
    with pytest.raises(RequestConflict):
        getattr(store, method)(
            "destination", "Summarize this", request_id="known-id", requested=CHOICES
        )
    assert store.get_session("destination") == before


def test_legacy_same_session_replay_compatibility(store):
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE client_requests SET digest_version=1,digest=?,execution_json='{}' WHERE request_id='known-id'",
            (input_fingerprint("Summarize this"),),
        )
    before = store.get_session("private-chat")
    status, body = handler(store, "private-chat")
    assert status == 200 and body["replayed"] and body["output"] == "PRIVATE ANSWER"
    assert store.get_session("private-chat") == before
    with pytest.raises(RequestConflict):
        store.admit_request(
            "private-chat", "different", request_id="known-id", requested=CHOICES
        )


@pytest.mark.parametrize("method", ["admit_request", "enqueue_request"])
@pytest.mark.parametrize("legacy", [False, True])
def test_same_session_enqueue_replay(store, method, legacy):
    receipt = store.enqueue_request(
        "queued", "Queued work", request_id="queued-id", requested=CHOICES
    )
    if legacy:
        with sqlite3.connect(store.path) as conn:
            conn.execute(
                "UPDATE client_requests SET digest_version=1,digest=?,execution_json='{}' WHERE request_id='queued-id'",
                (input_fingerprint("Queued work"),),
            )
    before = store.get_session("queued")
    replay = getattr(store, method)(
        "queued", "Queued work", request_id="queued-id", requested=CHOICES
    )
    assert replay["replayed"] and not replay["accepted"]
    assert replay["request_id"] == receipt["request_id"]
    assert store.get_session("queued") == before


@pytest.mark.parametrize(
    "status", ["admitted", "running", "queued", "execution_unknown"]
)
@pytest.mark.parametrize("method", ["admit_request", "enqueue_request"])
def test_foreign_inflight_receipts_are_rejected(store, status, method):
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE client_requests SET status=? WHERE request_id='known-id'", (status,)
        )
    with pytest.raises(RequestConflict):
        getattr(store, method)(
            "foreign", "Summarize this", request_id="known-id", requested=CHOICES
        )
    assert store.get_session("foreign") is None


def test_concurrent_sessions_cannot_share_request_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store = GatewaySessionStore(tmp_path / "race.sqlite3")
    barrier = Barrier(2)

    def admit(session_id):
        barrier.wait(timeout=5)
        try:
            return store.admit_request(
                session_id, "Concurrent work", request_id="race", requested=CHOICES
            )
        except RequestConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(admit, ["left", "right"]))
    accepted = [r for r in results if r is not None]
    assert len(accepted) == 1 and accepted[0]["accepted"]
    winner = accepted[0]["session_id"]
    loser = "right" if winner == "left" else "left"
    assert store.get_request("race")["session_id"] == winner
    assert store.get_session(loser) is None
