"""Search count is derived from actual durable tool lifecycle events."""

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def test_search_count_repeated_failed_empty_and_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)

    admitted = store.admit_request("session", "question", request_id="request")
    callbacks, flush = app._turn_stream_callbacks("session", "request")
    for name, ok in (("web_search", True), ("web_search", False), ("search_files", True)):
        callbacks.on_tool_progress(name, "start", {})
        callbacks.on_tool_done(name, {}, {}, ok, None if ok else "failed", 0.01)
    callbacks.on_tool_progress("read_file", "start", {})
    callbacks.on_tool_done("read_file", {}, {}, True, None, 0.01)
    flush()
    result = {"turn_id": admitted["turn_id"], "output": "answer"}
    app._persist_terminal("request", "session", "completed", result,
                          assistant_text="answer", record_entity_event=False)
    events = app.event_bus.get_replay_events("session")
    counts = [e for e in events if e.event == "search.count"]
    assert len(counts) == 1
    assert counts[0].data == {"session_id": "session", "request_id": "request",
                              "turn_id": admitted["turn_id"], "searches": 3,
                              "completed": 2, "failed": 1}
    names = [e.event for e in events]
    assert names.index("search.count") < names.index("turn.finish")
    app._persist_terminal("request", "session", "completed", result,
                          assistant_text="answer", record_entity_event=False)
    assert len([e for e in app.event_bus.get_replay_events("session")
                if e.event == "search.count"]) == 1

    empty = store.admit_request("session", "plain", request_id="empty")
    app._persist_terminal("empty", "session", "completed",
                          {"turn_id": empty["turn_id"], "output": "plain"},
                          assistant_text="plain", record_entity_event=False)
    assert not [e for e in app.event_bus.get_replay_events("session")
                if e.event == "search.count" and e.data.get("request_id") == "empty"]
