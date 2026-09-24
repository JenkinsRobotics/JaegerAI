"""Gateway contract for safe, durable tool lifecycle projection."""

from __future__ import annotations

import json

from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _admitted_app(tmp_path, *, session_id: str = "session", request_id: str = "request"):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)
    admitted = store.admit_request(session_id, "exercise tools", request_id=request_id)
    return app, store, admitted


def _request_events(app: JaegerGatewayApp, session_id: str, request_id: str):
    return [
        event
        for event in app.event_bus.get_replay_events(session_id)
        if event.data.get("request_id") == request_id
    ]


def test_tool_callbacks_preserve_text_order_and_distinguish_repeated_calls(tmp_path):
    app, _store, admitted = _admitted_app(tmp_path)
    callbacks, flush = app._turn_stream_callbacks("session", "request")

    callbacks.on_stream_delta("before ")
    callbacks.on_reasoning("checking")
    callbacks.on_tool_progress("read_file", "start", {"path": "/private/first"})
    callbacks.on_tool_progress("read_file", "start", {"path": "/private/second"})
    callbacks.on_tool_progress("read_file", "done", {"elapsed_s": 0.1})
    callbacks.on_tool_done(
        "read_file", {"path": "/private/first"}, {"content": "first"}, True, None, 0.1,
    )
    callbacks.on_tool_progress("read_file", "done", {"elapsed_s": 0.2})
    callbacks.on_tool_done(
        "read_file", {"path": "/private/second"}, {"content": "second"}, True, None, 0.2,
    )
    callbacks.on_stream_delta("after")
    flush()

    events = _request_events(app, "session", "request")
    assert [event.event for event in events] == [
        "turn.start",
        "turn.delta",
        "turn.reasoning",
        "turn.progress",
        "tool.started",
        "turn.progress",
        "tool.started",
        "tool.completed",
        "tool.completed",
        "turn.delta",
    ]
    assert [event.data.get("delta") for event in events if event.event == "turn.delta"] == [
        "before ",
        "after",
    ]

    starts = [event for event in events if event.event == "tool.started"]
    completions = [event for event in events if event.event == "tool.completed"]
    assert len({event.data["activity_id"] for event in starts}) == 2
    assert [event.data["activity_id"] for event in starts] == [
        event.data["activity_id"] for event in completions
    ]
    for event in starts + completions:
        assert event.data["call_id"] == event.data["activity_id"]
        assert event.data["session_id"] == "session"
        assert event.data["request_id"] == "request"
        assert event.data["turn_id"] == admitted["turn_id"]
        assert event.data["tool"] == "read_file"


def test_tool_failure_is_sanitized_and_replays_from_durable_cursor(tmp_path):
    app, store, _admitted = _admitted_app(tmp_path)
    callbacks, _flush = app._turn_stream_callbacks("session", "request")

    callbacks.on_tool_progress(
        "run_shell", "start", {"command": "echo SHOWN_COMMAND", "token": "ARG_TOKEN"},
    )
    callbacks.on_tool_progress("run_shell", "done", {"elapsed_s": 1.23456})
    callbacks.on_tool_done(
        "run_shell",
        {"command": "echo SHOWN_COMMAND"},
        {"ok": False, "error": "RESULT_SECRET"},
        False,
        "ERROR_SECRET",
        1.23456,
    )

    events = _request_events(app, "session", "request")
    started, failed = events[-2:]
    assert [started.event, failed.event] == ["tool.started", "tool.failed"]
    assert failed.data == {
        "turn_id": failed.data["turn_id"],
        "request_id": "request",
        "session_id": "session",
        "activity_id": started.data["activity_id"],
        "call_id": started.data["activity_id"],
        "tool": "run_shell",
        "phase": "failed",
        "success": False,
        "ok": False,
        "elapsed_s": 1.235,
        "text": "Failed after 1.235s",
    }
    # A shell command is shown inline on purpose; every other argument, the result
    # and the error are never published.
    assert started.data["input"] == "echo SHOWN_COMMAND"
    serialized = json.dumps([event.data for event in events])
    for secret in ("ARG_TOKEN", "RESULT_SECRET", "ERROR_SECRET"):
        assert secret not in serialized
    assert "args" not in failed.data
    assert "result" not in failed.data
    assert "error" not in failed.data

    # A new bus instance proves these are SQLite-backed cursor events, not an
    # in-memory projection owned by the original Gateway object.
    reopened = GatewayEventBus(store=GatewaySessionStore(store.path))
    replay = reopened.get_replay_events("session", since_event_id=started.event_id - 1)
    assert [(event.event_id, event.event, event.data) for event in replay] == [
        (started.event_id, started.event, started.data),
        (failed.event_id, failed.event, failed.data),
    ]


def test_malformed_tool_name_is_not_copied_to_client_events(tmp_path):
    app, _store, _admitted = _admitted_app(tmp_path)
    callbacks, _flush = app._turn_stream_callbacks("session", "request")

    callbacks.on_tool_progress("run_shell\nNAME_SECRET", "start", {})
    callbacks.on_tool_done(
        "run_shell\nNAME_SECRET", {}, {"ok": True}, True, None, 0.01,
    )

    events = _request_events(app, "session", "request")[-2:]
    assert [event.data["tool"] for event in events] == ["tool", "tool"]
    assert "NAME_SECRET" not in json.dumps([event.data for event in events])


def test_owner_react_path_installs_tool_callbacks_and_flushes_after_tool(monkeypatch, tmp_path):
    app, store, _admitted = _admitted_app(tmp_path)

    class Runtime:
        def run_subordinate_react(self, prompt, *, callbacks, **_kwargs):
            assert prompt == "exercise tools"
            callbacks.on_stream_delta("alpha")
            callbacks.on_tool_progress("read_file", "start", {"path": "OWNER_ARG_SECRET"})
            callbacks.on_tool_progress("read_file", "done", {"elapsed_s": 0.01})
            callbacks.on_tool_done(
                "read_file", {"path": "OWNER_ARG_SECRET"}, {"content": "OWNER_RESULT_SECRET"},
                True, None, 0.01,
            )
            callbacks.on_stream_delta("omega")
            return {"text": "alphaomega", "halt_reason": None}

    from jaeger_ai.core.entity.runtime import EntityRuntime

    monkeypatch.setattr(
        EntityRuntime,
        "get_singleton",
        classmethod(lambda cls, *args, **kwargs: Runtime()),
    )
    result = app._owner_react_turn(
        "exercise tools", session_key="session", request_id="request", execution={},
    )

    assert result["text"] == "alphaomega"
    replay = GatewaySessionStore(store.path).replay_events("session")["events"]
    request_events = [event for event in replay if event["data"].get("request_id") == "request"]
    assert [event["event"] for event in request_events] == [
        "turn.start", "turn.delta", "turn.progress", "tool.started", "tool.completed", "turn.delta",
    ]
    serialized = json.dumps(request_events)
    assert "OWNER_ARG_SECRET" not in serialized
    assert "OWNER_RESULT_SECRET" not in serialized


def _events_named(app, session_id, request_id, name):
    return [e for e in _request_events(app, session_id, request_id) if e.event == name]


def test_update_plan_result_is_published_as_a_turn_plan_event(tmp_path):
    app, _store, _ = _admitted_app(tmp_path)
    callbacks, flush = app._turn_stream_callbacks("session", "request")
    plan = {
        "ok": True, "explanation": "starting",
        "plan": [{"step": "read", "status": "completed"}, {"step": "fix", "status": "in_progress"}],
        "summary": {"total": 2, "pending": 0, "in_progress": 1, "completed": 1},
    }
    callbacks.on_tool_progress("update_plan", "start", {"plan": "ignored"})
    callbacks.on_tool_done("update_plan", {}, plan, True, None, 0.01)
    flush()
    (event,) = _events_named(app, "session", "request", "turn.plan")
    assert event.data["plan"] == [
        {"step": "read", "status": "completed"}, {"step": "fix", "status": "in_progress"},
    ]
    assert event.data["explanation"] == "starting"
    assert event.data["summary"]["in_progress"] == 1


def test_only_update_plan_results_are_ever_published(tmp_path):
    app, _store, _ = _admitted_app(tmp_path)
    callbacks, flush = app._turn_stream_callbacks("session", "request")
    leaky = {"ok": True, "plan": [{"step": "SECRET-TOKEN", "status": "pending"}], "summary": {}}
    callbacks.on_tool_progress("read_file", "start", {"path": "/p"})
    callbacks.on_tool_done("read_file", {}, leaky, True, None, 0.01)  # not update_plan
    callbacks.on_tool_progress("update_plan", "start", {})
    callbacks.on_tool_done("update_plan", {}, {"ok": False, "error": "SECRET-TOKEN"}, True, None, 0.01)
    callbacks.on_tool_progress("update_plan", "start", {})
    callbacks.on_tool_done("update_plan", {}, leaky, False, "SECRET-TOKEN", 0.01)  # tool failed
    flush()
    assert _events_named(app, "session", "request", "turn.plan") == []
    assert "SECRET-TOKEN" not in str([e.data for e in _request_events(app, "session", "request")])


def test_oversized_plans_are_bounded(tmp_path):
    app, _store, _ = _admitted_app(tmp_path)
    callbacks, flush = app._turn_stream_callbacks("session", "request")
    big = {"ok": True, "plan": [{"step": "x" * 5000, "status": "pending"}] * 200, "summary": {}}
    callbacks.on_tool_progress("update_plan", "start", {})
    callbacks.on_tool_done("update_plan", {}, big, True, None, 0.01)
    flush()
    (event,) = _events_named(app, "session", "request", "turn.plan")
    assert len(event.data["plan"]) == 50 and len(event.data["plan"][0]["step"]) == 500


def test_shell_commands_and_output_are_shown_inline_with_secrets_redacted_and_nothing_else(tmp_path):
    app, _store, _ = _admitted_app(tmp_path)
    callbacks, flush = app._turn_stream_callbacks("session", "request")
    callbacks.on_tool_progress("exec_command", "start", {"cmd": "curl -H 'Authorization: Bearer sk-abcdef1234567890' x"})
    callbacks.on_tool_done("exec_command", {}, {"output": "ok\nAPI_KEY=supersecretvalue123", "exit_code": 0}, True, None, 0.1)
    callbacks.on_tool_progress("read_file", "start", {"path": "/p", "content": "FILE-BODY"})
    callbacks.on_tool_done("read_file", {}, {"content": "FILE-BODY"}, True, None, 0.1)
    flush()
    events = _request_events(app, "session", "request")
    started = [e for e in events if e.event == "tool.started"]
    done = [e for e in events if e.event == "tool.completed"]
    assert "sk-***" in started[0].data["input"] and "abcdef1234567890" not in started[0].data["input"]
    assert "API_KEY=***" in done[0].data["output"] and "supersecretvalue123" not in done[0].data["output"]
    assert "input" not in started[1].data and "output" not in done[1].data  # file tools publish nothing
    assert "FILE-BODY" not in str([e.data for e in events])
