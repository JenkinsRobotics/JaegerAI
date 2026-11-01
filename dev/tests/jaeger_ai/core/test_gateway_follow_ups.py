"""Explicit completion suggestions are bounded, ordered, and durable."""

from jaeger_ai.core.gateway.server import JaegerGatewayApp, _explicit_follow_ups
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_follow_ups_are_explicit_and_bounded():
    assert _explicit_follow_ups({"output": "What next?"}) == []
    assert _explicit_follow_ups({"follow_ups": "What next?"}) == []
    assert _explicit_follow_ups({"follow_ups": ["  First  ", "", "x" * 161, 7, "Second", "Third", "Fourth", "Fifth", "Sixth"]}) == [
        "First", "Second", "Third", "Fourth", "Fifth"]


def test_follow_ups_follow_final_delta_and_precede_finish_with_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)
    admitted = store.admit_request("session", "question", request_id="request")
    callbacks, flush = app._turn_stream_callbacks("session", "request")
    callbacks.on_stream_delta("answer")
    flush()
    result = {"turn_id": admitted["turn_id"], "output": "answer", "follow_ups": ["Next question?"]}
    app._persist_terminal("request", "session", "completed", result, assistant_text="answer", record_entity_event=False)
    events = [e for e in app.event_bus.get_replay_events("session") if e.data.get("request_id") == "request"]
    names = [e.event for e in events]
    assert names.index("turn.delta") < names.index("follow_ups") < names.index("turn.finish")
    assert events[names.index("follow_ups")].data == {
        "request_id": "request", "turn_id": admitted["turn_id"], "follow_ups": ["Next question?"]}
    app._persist_terminal("request", "session", "completed", result, assistant_text="answer", record_entity_event=False)
    assert len([e for e in app.event_bus.get_replay_events("session") if e.event == "follow_ups"]) == 1
