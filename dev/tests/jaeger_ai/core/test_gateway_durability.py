"""Regression proofs for completion, replay and single gateway ownership."""
import asyncio
import os

import pytest

from jaeger_ai.core.gateway.event_bus import GatewayEventBus, ReplayGap
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_completed_receipt_cannot_be_overwritten(tmp_path):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    store.admit_request("s", "work", request_id="immutable")
    finished = store.complete_request("immutable", status="completed", result={"output": "done"}, assistant_text="done")
    assert finished["event"]["event"] == "turn.finish"
    late = store.complete_request("immutable", status="failed", result={"error": "late"}, assistant_text="bad")
    assert late["status"] == "completed"
    assert late["result"] == {"output": "done"}
    assert late["replayed"] is True
    reopened = GatewaySessionStore(store.path)
    assert [m["content"] for m in reopened.get_session("s")["messages"]] == ["work", "done"]
    assert [e["event"] for e in reopened.replay_events("s")["events"]] == ["turn.start", "turn.finish"]


def test_terminal_event_failure_rolls_back_receipt_and_transcript(tmp_path, monkeypatch):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    store.admit_request("s", "work", request_id="atomic")
    def fail(*args):
        raise OSError("event storage failed")
    monkeypatch.setattr(store, "_insert_event", fail)
    with pytest.raises(OSError):
        store.complete_request("atomic", status="completed", result={"output": "done"}, assistant_text="done")
    assert store.get_request("atomic")["status"] == "admitted"
    assert len(store.get_session("s")["messages"]) == 1


@pytest.mark.asyncio
async def test_every_replay_page_and_slow_subscriber_remain_ordered(tmp_path):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    bus = GatewayEventBus(store=store)
    for i in range(501):
        bus.publish("s", "delta", {"n": i})
    stream = bus.subscribe("s")
    first = await anext(stream)
    assert first.event_id == 1
    # Publish more than the former subscriber queue capacity while paused.
    for i in range(501, 1101):
        bus.publish("s", "delta", {"n": i})
    got = [first.event_id]
    for _ in range(1100):
        got.append((await asyncio.wait_for(anext(stream), 1)).event_id)
    assert got == list(range(1, 1102))
    await stream.aclose()


def test_interleaved_sessions_do_not_expire_valid_cursor(tmp_path):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    first = store.append_event("s", "one", {})
    for _ in range(10):
        store.append_event("elsewhere", "other", {})
    store.append_event("s", "two", {})
    store.append_event("*", "approval.request", {})
    replay = store.replay_events("s", first["event_id"])
    assert replay["valid_cursor"]
    assert [e["event"] for e in replay["events"]] == ["two", "approval.request"]


@pytest.mark.asyncio
async def test_retention_gap_is_reported_instead_of_hanging(tmp_path, monkeypatch):
    import jaeger_ai.core.gateway.session_store as module
    monkeypatch.setattr(module, "MAX_RETAINED_EVENTS", 3)
    store = GatewaySessionStore(tmp_path / "sessions.db")
    bus = GatewayEventBus(store=store)
    bus.publish("s", "one", {})
    stream = bus.subscribe("s")
    await anext(stream)
    for _ in range(5):
        bus.publish("s", "later", {})
    with pytest.raises(ReplayGap):
        await asyncio.wait_for(anext(stream), 1)
    assert not store.replay_events("s", 1)["valid_cursor"]


@pytest.mark.asyncio
async def test_foreign_owner_prevents_startup_and_cleanup_mutations(tmp_path):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    store.admit_request("s", "running work", request_id="foreign")
    store.claim_process(pid=os.getppid())
    app = JaegerGatewayApp(store=store)
    with pytest.raises(RuntimeError, match="owned by live pid"):
        await app._recover_interrupted(app.app)
    await app._bounded_shutdown(app.app)
    assert store.get_request("foreign")["status"] == "admitted"
    assert store.process_lease()["owner_pid"] == os.getppid()


@pytest.mark.asyncio
async def test_native_type_error_does_not_execute_twice(tmp_path, monkeypatch):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    row = store.admit_request("s", "work", request_id="one-dispatch")
    app = JaegerGatewayApp(store=store)
    calls = []
    async def native(*args, **kwargs):
        calls.append(kwargs)
        store.bind_native(
            row["request_id"],
            native_run_id=row["request_id"],
            native_session="native-session",
            status="running",
        )
        raise TypeError("after effect")
    monkeypatch.setattr(app, "_resolve_session_agent", lambda _: None)
    monkeypatch.setattr(app, "_native_lead_turn", native)
    await app._execute_turn("s", row["turn_id"], "work", request_id=row["request_id"])
    assert len(calls) == 1
    assert store.get_request(row["request_id"])["status"] == "execution_unknown"


@pytest.mark.asyncio
async def test_confirmed_native_halt_is_failed_not_unknown(tmp_path, monkeypatch):
    store = GatewaySessionStore(tmp_path / "sessions.db")
    row = store.admit_request("s", "research", request_id="halt")
    app = JaegerGatewayApp(store=store)
    async def native(*args, **kwargs): return None
    monkeypatch.setattr(app, "_resolve_session_agent", lambda _: None)
    monkeypatch.setattr(app, "_native_lead_turn", native)
    monkeypatch.setattr(app, "_native_receipt", lambda *args: {
        "status": "failed", "execution_unknown": False,
        "reply": {"halt_reason": "repeated_tool_failure"}})
    await app._execute_turn("s", row["turn_id"], "research", request_id="halt")
    assert store.get_request("halt")["status"] == "failed"
    assert [e.event for e in app.event_bus.get_replay_events("s")] == ["turn.start", "turn.failed"]


def test_handoff_terminal_result_is_immutable(tmp_path):
    store = GatewaySessionStore(tmp_path / 'sessions.db')
    row = {'id': 'handoff_1', 'request_id': 'r', 'from_agent_id': 'lead',
           'to_agent_id': 'child', 'task': 'work', 'status': 'completed',
           'result': {'ok': True, 'summary': 'done'}}
    store.save_handoff(row)
    late = store.save_handoff({**row, 'status': 'failed', 'result': {'error': 'late'}})
    assert late['status'] == 'completed'
    assert late['result']['summary'] == 'done'


@pytest.mark.asyncio
async def test_handoff_observation_reconciles_native_receipt_without_execution(tmp_path, monkeypatch):
    store = GatewaySessionStore(tmp_path / 'sessions.db')
    store.save_handoff({'id': 'handoff_late', 'request_id': 'request', 'from_agent_id': 'lead',
                        'to_agent_id': 'child', 'task': 'work', 'status': 'execution_unknown'})
    app = JaegerGatewayApp(store=store)
    def receipt(native_id, session):
        assert len(native_id) == 64 and session == 'specialist:child:request'
        return {'status': 'completed', 'execution_unknown': False, 'reply': {'text': 'late result'}}
    monkeypatch.setattr(app, '_native_receipt', receipt)
    class Request:
        match_info = {'id': 'handoff_late'}
    await app.handle_get_handoff(Request())
    assert store.get_handoff('handoff_late')['result']['summary'] == 'late result'
    assert not app._running_tasks
