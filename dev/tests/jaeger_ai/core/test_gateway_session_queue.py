"""Gateway-owned durable session queue contract."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import (
    GatewaySessionStore,
    RequestConflict,
)


class _Request:
    def __init__(self, match_info: dict, body: dict | None = None, *, method: str = "GET") -> None:
        self.match_info = match_info
        self._body = body or {}
        self.can_read_body = True
        self.method = method

    async def json(self):
        return self._body


def _body(response) -> dict:
    return json.loads(response.text)


def test_queue_event_is_part_of_the_gateway_stream_contract():
    assert "queue.updated" in EVENT_TYPES


def test_durable_queue_survives_store_restart_and_preserves_order(tmp_path: Path):
    path = tmp_path / "gateway.sqlite3"
    store = GatewaySessionStore(path)
    store.enqueue_request("session", "first", request_id="q1")
    second = store.enqueue_request("session", "second", request_id="q2", requested={"model": "glm"})
    assert store.schema_version() == 15  # Current canonical schema; queue was introduced at12.
    import sqlite3
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute('PRAGMA table_info(client_requests)')}
    assert {'queue_position', 'execution_json', 'request_id', 'status'} <= columns
    assert [row["request_id"] for row in store.list_queue("session")] == ["q1", "q2"]
    assert second["execution"]["model"] == "glm"

    reopened = GatewaySessionStore(path)
    queue = reopened.list_queue("session")
    assert [row["request_id"] for row in queue] == ["q1", "q2"]
    assert queue[1]["execution"]["model"] == "glm"


def test_editing_a_queued_item_preserves_its_execution_choices(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.enqueue_request("session", "original", request_id="q1", requested={"model": "glm"})
    updated = store.update_queue_item("session", "q1", text="edited")
    assert updated is not None
    assert updated["input_text"] == "edited"
    assert updated["execution"]["model"] == "glm"

    # The same request identity cannot silently become a different queue item.
    try:
        store.enqueue_request("session", "conflicting", request_id="q1")
    except RequestConflict:
        pass
    else:
        raise AssertionError("edited queue item must retain its request identity")


def test_paused_items_do_not_auto_promote(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.enqueue_request("session", "ready", request_id="q1")
    paused = store.enqueue_request("session", "paused", request_id="q2")
    store.update_queue_item("session", paused["request_id"], status="paused")

    promoted = store.promote_next_queue_item("session")
    assert promoted is not None
    assert promoted["request_id"] == "q1"
    assert [row["request_id"] for row in store.list_queue("session")] == ["q2"]
    assert store.promote_next_queue_item("session") is None


def test_busy_session_cannot_promote_queue_work(tmp_path: Path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    active = store.admit_request("session", "active work", request_id="active")
    store.enqueue_request("session", "follow-up", request_id="queued")
    assert active["status"] == "admitted"
    assert store.promote_next_queue_item("session") is None
    assert [row["request_id"] for row in store.list_queue("session")] == ["queued"]


def test_queue_add_publishes_durable_projection_and_starts_when_idle(tmp_path: Path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("session")
    started: list[dict] = []
    app._start_admitted_turn = lambda admitted, sid, text: started.append(
        {"sid": sid, "rid": admitted["request_id"], "text": text}
    )

    response = asyncio.run(app.handle_add_queue(_Request(
        {"id": "session"}, {"text": "follow-up work", "request_id": "q1"},
        method="POST",
    )))
    payload = _body(response)
    assert response.status == 202
    assert payload["status"] == "admitted"  # Dispatch is not proof that execution started.
    assert started == [{"sid": "session", "rid": "q1", "text": "follow-up work"}]
    events = app.event_bus.get_replay_events("session")
    assert [event.event for event in events if event.event != "message.created"] == ["turn.start", "queue.updated"]
    assert events[-1].data["items"] == []
    assert app.store.get_request("q1")["status"] == "admitted"


def test_queue_add_while_busy_returns_a_durable_queued_request(tmp_path: Path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.admit_request("session", "current work", request_id="active")
    started: list[str] = []
    app._start_admitted_turn = lambda *args: started.append("must not start")

    response = asyncio.run(app.handle_add_queue(_Request(
        {"id": "session"}, {"text": "follow-up work", "request_id": "q1"},
        method="POST",
    )))
    payload = _body(response)
    assert response.status == 202
    assert payload["queued"] is True
    assert payload["status"] == "queued"
    assert started == []
    assert [row["request_id"] for row in app.store.list_queue("session")] == ["q1"]

    queue_event = [e for e in app.event_bus.get_replay_events("session") if e.event == "queue.updated"]
    assert queue_event and queue_event[0].data["items"][0]["request_id"] == "q1"


def test_queue_reorder_is_atomic_and_rejects_partial_orders(tmp_path: Path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.admit_request("session", "active", request_id="active")
    app.store.enqueue_request("session", "first", request_id="q1")
    app.store.enqueue_request("session", "second", request_id="q2")

    response = asyncio.run(app.handle_reorder_queue(_Request(
        {"id": "session"}, {"order": ["q2", "q1"]}, method="POST",
    )))
    assert response.status == 200
    assert [row["request_id"] for row in _body(response)["items"]] == ["q2", "q1"]

    bad = asyncio.run(app.handle_reorder_queue(_Request(
        {"id": "session"}, {"order": ["q1"]}, method="POST",
    )))
    assert bad.status == 400
    assert [row["request_id"] for row in app.store.list_queue("session")] == ["q2", "q1"]


def test_terminal_outcome_drains_the_next_queue_item_once(tmp_path: Path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("session")
    app.store.admit_request("session", "current work", request_id="active")
    app.store.enqueue_request("session", "follow-up", request_id="q1")
    started: list[str] = []
    app._start_admitted_turn = lambda admitted, sid, text: started.append(admitted["request_id"])

    app._persist_terminal("active", "session", "completed", {"output": "done"}, assistant_text="done")
    assert started == ["q1"]
    assert app.store.get_request("q1")["status"] == "admitted"
    assert app.store.list_queue("session") == []
    events = [event.event for event in app.event_bus.get_replay_events("session") if event.event != "message.created"]
    assert events == ["turn.start", "turn.finish", "turn.start", "queue.updated"]


def test_new_queue_receipt_never_borrows_an_older_promoted_request_identity(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    first = app.store.enqueue_request('session', 'older queued', request_id='older')
    started = []
    app._start_admitted_turn = lambda row, *args: started.append(row['request_id'])
    response = asyncio.run(app.handle_add_queue(_Request({'id':'session'}, {'text':'new follow-up','request_id':'newer'}, method='POST')))
    payload = _body(response)
    assert started == ['older']
    assert payload['request_id'] == 'newer' and payload['status'] == 'queued' and payload['queued']
    assert payload['turn_id'] != first['turn_id']
    assert payload['turn_id'] == app.store.get_request('newer')['turn_id']
    assert 'start_event_id' not in payload


def test_queue_edit_version_conflict_preserves_newer_text_and_execution(tmp_path):
    import pytest
    store = GatewaySessionStore(tmp_path/'gateway.sqlite3')
    row = store.enqueue_request('session', 'Original', request_id='owned', requested={'model':'configured'})
    updated = store.update_queue_item('session', 'owned', text='Newer', expected_updated_at=row['updated_at'])
    with pytest.raises(RequestConflict):
        store.update_queue_item('session', 'owned', text='Stale overwrite', expected_updated_at=row['updated_at'])
    current = store.get_request('owned')
    assert current['input_text'] == 'Newer' and current['execution'] == updated['execution']
    assert current['turn_id'] == row['turn_id'] and current['status'] == 'queued'
