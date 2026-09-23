"""Background delivery survives detached clients, restarts and lost ACKs."""
import asyncio
import io
import threading
from types import SimpleNamespace

import pytest

from jaeger_ai.core.sessions import get_store, reset_for_tests
from jaeger_ai.core.runtime.background_delivery import record_result
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore, RequestConflict
from jaeger_ai.interfaces import bridge


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "jaeger"
    (root / "memory").mkdir(parents=True)
    lay = SimpleNamespace(root=root, memory_dir=root / "memory")
    yield lay
    reset_for_tests()


def result(layout, **kwargs):
    return record_result(layout, {"text": "Your requested research has finished.", **kwargs},
                         source="heartbeat", source_session="heartbeat", display_name="Assistant",
                         delivery_id="beat-1")


def test_native_result_and_transcript_survive_restart_once(layout):
    row = result(layout)
    assert result(layout) == row
    with pytest.raises(ValueError, match="conflicts"):
        result(layout, text="different result")
    reset_for_tests()
    store = get_store(layout)
    assert store.background_messages() == [row]
    messages = store.history("dispatcher")
    assert len(messages) == 1 and messages[0]["text"] == row["text"]
    store.acknowledge_background("beat-1")
    reset_for_tests()
    assert get_store(layout).background_messages() == []
    assert len(get_store(layout).history("dispatcher")) == 1


def test_native_transcript_failure_rolls_back_outbox(layout):
    store = get_store(layout)
    store._conn.execute("CREATE TRIGGER fail_message BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT,'disk failure'); END")
    with pytest.raises(Exception, match="disk failure"):
        result(layout)
    assert store.background_messages() == []


def test_cron_type_error_after_effect_does_not_repeat_execution():
    from jaeger_agent.background.cron_runner import CronRunner
    effects = []
    def callback(prompt, session_key=None):
        effects.append(session_key)
        raise TypeError("raised after effect")
    with pytest.raises(TypeError):
        CronRunner(callback)._invoke("work", "one-shot")
    assert effects == ["cron:one-shot"]
    legacy = []
    CronRunner(lambda prompt: legacy.append(prompt))._invoke("legacy", "one-shot")
    assert legacy == ["legacy"]


@pytest.mark.parametrize("text", ["", "HEARTBEAT_OK", "[SILENT]"])
def test_silent_success_has_no_message(layout, text):
    assert result(layout, text=text) is None
    assert get_store(layout).background_messages() == []


@pytest.mark.parametrize("fields,status", [
    ({"halt_reason": "repeated_tool_failure"}, "failed"),
    ({"error": "provider down"}, "failed"),
    ({"cancelled": True}, "cancelled"),
    ({"execution_unknown": True}, "execution_unknown"),
])
def test_failure_is_not_silent_or_claimed_complete(layout, fields, status):
    row = result(layout, text="HEARTBEAT_OK", **fields)
    assert row["status"] == status
    assert "Background heartbeat " + status in row["text"]


class LocalBridge:
    def __init__(self, layout):
        self.boot = SimpleNamespace(layout=layout)
        self.lose_ack = False

    def query(self, name, args, **kwargs):
        return bridge._query(name, args, self.boot)

    def command(self, name, args):
        if self.lose_ack:
            raise ConnectionError("ACK transport lost")
        ok, error = bridge._command(name, args, self.boot)
        if not ok:
            raise RuntimeError(error)


@pytest.mark.asyncio
async def test_gateway_restart_lost_ack_two_clients_and_replay(layout, tmp_path):
    row = result(layout)
    client = LocalBridge(layout)
    store = GatewaySessionStore(tmp_path / "gateway.db")
    app = JaegerGatewayApp(store=store, background_client=client)
    first = app.event_bus.subscribe("dispatcher")
    second = app.event_bus.subscribe("dispatcher")
    waiting = [asyncio.create_task(anext(s)) for s in (first, second)]
    client.lose_ack = True
    with pytest.raises(ConnectionError):
        await app._collect_background()
    events = await asyncio.wait_for(asyncio.gather(*waiting), 2)
    assert events[0].event_id == events[1].event_id
    assert events[0].event == "message.created"
    assert events[0].data["display_name"] == "Assistant"
    assert get_store(layout).background_messages() == [row]
    # New gateway object, same disk, no source execution or repeat message.
    restarted = JaegerGatewayApp(store=GatewaySessionStore(store.path), background_client=client)
    client.lose_ack = False
    assert await restarted._collect_background() == 1
    assert get_store(layout).background_messages() == []
    assert len(restarted.store.get_session("dispatcher")["messages"]) == 1
    replay = restarted.store.replay_events("dispatcher")["events"]
    assert len(replay) == 1 and replay[0]["event_id"] == events[0].event_id
    for stream in (first, second):
        await stream.aclose()


@pytest.mark.asyncio
async def test_gateway_failed_commit_keeps_native_pending(layout, tmp_path, monkeypatch):
    result(layout)
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "g.db"), background_client=LocalBridge(layout))
    def fail(*args):
        raise OSError("event write failed")
    monkeypatch.setattr(app.store, "_insert_event", fail)
    with pytest.raises(OSError):
        await app._collect_background()
    assert app.store.get_session("dispatcher") is None
    assert len(get_store(layout).background_messages()) == 1


def test_gateway_conflict_and_deleted_session_do_not_duplicate(layout, tmp_path):
    row = result(layout)
    store = GatewaySessionStore(tmp_path / "g.db")
    receipt = store.receive_background(row)
    with pytest.raises(RequestConflict):
        store.receive_background({**row, "text": "replaced"})
    store.delete_session("dispatcher")
    retry = store.receive_background(row)
    assert retry["message_id"] == receipt["message_id"] and retry["replayed"]
    assert store.get_session("dispatcher") is None


def test_dispatcher_knows_its_background_message_after_ack(layout):
    from jaeger_ai.features.dispatcher.store import context_note
    row = result(layout)
    get_store(layout).acknowledge_background(row["delivery_id"])
    note = context_note(layout, "dispatcher")
    assert row["text"] in note and "does not prove the human read" in note


@pytest.mark.parametrize("operation", ["clear", "delete"])
def test_native_conversation_removal_cancels_pending_delivery(layout, operation):
    result(layout)
    store = get_store(layout)
    getattr(store, operation)("dispatcher")
    assert store.background_messages() == []
    assert store.background_messages(pending=False) == []


def test_idle_tick_does_not_enter_a_foreground_workspace(layout, monkeypatch):
    ctx = bridge._Ctx()
    ctx.layout = layout
    entered = []
    monkeypatch.setattr(bridge, "_idle_once_locked", lambda *args: entered.append(True))
    with ctx.workspace_lock:
        thread = threading.Thread(target=bridge._idle_once, args=(io.StringIO(), ctx))
        thread.start(); thread.join(timeout=1)
        assert not thread.is_alive() and not entered
    bridge._idle_once(io.StringIO(), ctx)
    assert entered == [True]


def test_heartbeat_uses_character_path_and_durable_delivery(layout, monkeypatch):
    from jaeger_ai import main
    from jaeger_ai.core.runtime import heartbeat, idle_supervisor, completions
    from jaeger_agent.background import board
    ctx = bridge._Ctx()
    ctx.layout, ctx.client = layout, object()
    calls = []
    monkeypatch.setattr(board, "has_actionable_work", lambda *a: False)
    monkeypatch.setattr(completions, "pending_count", lambda: 0)
    monkeypatch.setattr(idle_supervisor, "decide", lambda **kw: idle_supervisor.Action.HEARTBEAT)
    monkeypatch.setattr(
        heartbeat,
        "execute_heartbeat_event",
        lambda *a, **kw: (object(), True, "Scheduled check"),
    )
    monkeypatch.setattr(main, "run_for_voice", lambda client, prompt, **kw: calls.append(kw) or {"text": "A useful update"})
    monkeypatch.setattr(main, "_run_turn", lambda *a, **kw: pytest.fail("persona bypass"))
    bridge._idle_once(io.StringIO(), ctx)
    assert calls == [{"session_key": "heartbeat"}]
    row = get_store(layout).background_messages()[0]
    assert row["session_id"] == "dispatcher" and row["text"] == "A useful update"
