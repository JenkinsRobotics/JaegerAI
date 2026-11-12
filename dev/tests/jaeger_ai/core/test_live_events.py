"""Live events: canonical trace envelope, scoped resumable replay, lifecycle hooks."""
from __future__ import annotations

import asyncio

import pytest

from jaeger_agent.hooks import HookDecision, HookRegistry
from jaeger_ai.contract import trace
from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.hooks_bridge import install
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _run(bus, sid="s1", rid="r1"):
    ids = {"request_id": rid, "turn_id": "t1"}
    bus.publish(sid, "turn.start", {**ids, "text": "hi"})
    bus.publish(sid, "model.started", {**ids, "step_id": f"{rid}:1", "index": 1})
    bus.publish(sid, "turn.delta", {**ids, "step_id": f"{rid}:1", "delta": "x"})
    bus.publish(sid, "model.finished", {**ids, "step_id": f"{rid}:1", "index": 1, "ok": True})
    bus.publish(sid, "tool.started", {**ids, "step_id": f"{rid}:1", "call_id": "c1", "tool": "list_dir"})
    bus.publish(sid, "approval.request", {**ids, "approval_id": "a1", "kind": "tool", "call_id": "c1", "session_id": sid})
    bus.publish("*", "approval.resolved", {**ids, "approval_id": "a1", "approved": True, "call_id": "c1", "session_id": sid})
    bus.publish(sid, "tool.completed", {**ids, "step_id": f"{rid}:1", "call_id": "c1", "tool": "list_dir", "elapsed_s": 0.05})
    bus.publish(sid, "turn.finish", {**ids, "status": "completed"})


@pytest.fixture
def store(tmp_path):
    return GatewaySessionStore(tmp_path / "gw.sqlite")


def test_every_turn_event_carries_one_tree(store):
    bus = GatewayEventBus(store=store)
    _run(bus)
    events = {e.event: e.trace for e in bus.get_replay_events("s1") if e.trace}
    assert events["turn.start"]["span_id"] == "run:r1" and events["turn.start"]["state"] == "running"
    assert events["model.started"]["parent_span_id"] == "run:r1"
    assert events["tool.started"]["span_id"] == "tool:c1"
    assert events["tool.started"]["parent_span_id"] == "step:r1:1"
    assert events["approval.request"]["parent_span_id"] == "tool:c1"
    assert events["approval.request"]["state"] == "waiting"
    assert events["approval.resolved"]["state"] == "succeeded"
    assert events["tool.completed"]["state"] == "succeeded"
    assert events["tool.completed"]["duration_ms"] is not None
    assert events["turn.finish"]["state"] == "succeeded" and events["turn.finish"]["agui"] == "RUN_FINISHED"
    seqs = [e.trace["seq"] for e in bus.get_replay_events("s1") if e.trace]
    assert all("trace" not in e.data for e in bus.get_replay_events("s1"))
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


def test_annotation_is_idempotent_and_skips_unrelated():
    data = trace.annotate("s", "tool.started", {"request_id": "rx", "call_id": "k", "tool": "t"})
    assert trace.annotate("s", "tool.started", data) is data
    assert "trace" not in trace.annotate("*", "backlog.updated", {"task_id": "b"})


def test_session_scope_excludes_unrelated_global_events(store):
    bus = GatewayEventBus(store=store)
    for i in range(5):
        bus.publish("*", "backlog.updated", {"task_id": f"b{i}"})
    _run(bus)
    scoped = store.replay_events("s1", 0, session_only=True)["events"]
    names = [e["event"] for e in scoped]
    assert "backlog.updated" not in names
    assert "approval.resolved" in names  # global, but names this session
    assert len(store.replay_events("s1", 0)["events"]) == len(scoped) + 5


def test_resume_from_cursor_replays_only_newer(store):
    bus = GatewayEventBus(store=store)
    _run(bus)
    all_ids = [e.event_id for e in bus.get_replay_events("s1")]
    cursor = all_ids[3]

    async def take():
        got = []
        async for evt in bus.subscribe("s1", since_event_id=cursor, session_only=True):
            got.append(evt.event_id)
            if evt.event == "turn.finish":
                break
        return got

    got = asyncio.run(asyncio.wait_for(take(), 5))
    assert got and min(got) > cursor and got == sorted(got)


def test_pre_tool_deny_wins_and_failures_fail_closed():
    reg = HookRegistry()
    reg.register("pre_tool", lambda t, a: HookDecision.modify({**a, "x": 2}))
    reg.register("pre_tool", lambda t, a: HookDecision.deny("no") if t == "rm" else None)
    assert reg.pre_tool("ls", {"x": 1}).args == {"x": 2}
    assert reg.pre_tool("rm", {}).action == "deny"
    reg2 = HookRegistry()
    reg2.register("pre_tool", lambda t, a: 1 / 0)
    assert reg2.pre_tool("ls", {}).action == "deny"


def test_matcher_and_observers_never_raise():
    reg = HookRegistry()
    calls = []
    reg.register("pre_tool", lambda t, a: calls.append(t), matcher="web_*")
    reg.pre_tool("list_dir", {})
    reg.pre_tool("web_search", {})
    assert calls == ["web_search"]
    reg.register("post_tool", lambda t, a, r: {"ok": True, "redacted": True})
    assert reg.post_tool("x", {}, {"ok": True, "secret": 1}) == {"ok": True, "redacted": True}
    reg.register("on_error", lambda p: 1 / 0)
    reg.fire("on_error", {})  # swallowed
    with pytest.raises(ValueError):
        reg.register("nope", lambda: None)


def test_hooked_executor_honours_deny_and_modify(monkeypatch):
    from jaeger_agent import hooks, tool_executor

    seen = {}

    class Inner:
        def execute(self, tool, args):
            seen.update(args)
            return {"ok": True}

    class Tool:
        name = "probe_tool"

    monkeypatch.setattr(tool_executor, "_jaeger_ai_installed", lambda: False)
    import jaeger_agent.core.host as host
    monkeypatch.setattr(host, "service", lambda name: (_ for _ in ()).throw(ImportError(name)))
    off = hooks.register("pre_tool", lambda t, a: HookDecision.modify({**a, "safe": True}), matcher="probe_*")
    try:
        out = tool_executor.HookedToolExecutor(Inner()).execute(Tool(), {"q": 1})
        assert out == {"ok": True} and seen == {"q": 1, "safe": True}
    finally:
        off()
    off = hooks.register("pre_tool", lambda t, a: HookDecision.deny("blocked for test"))
    try:
        out = tool_executor.HookedToolExecutor(Inner()).execute(Tool(), {})
        assert out["error_type"] == "blocked_by_hook" and out["error"] == "blocked for test"
    finally:
        off()


def test_bridge_fires_turn_end_approval_error_once(store):
    bus = GatewayEventBus(store=store)
    reg = HookRegistry()
    got: dict[str, list[str]] = {"on_turn_end": [], "on_approval": [], "on_error": []}
    for point in got:
        reg.register(point, lambda p, point=point: got[point].append(p["event"]))
    install(bus, reg)
    _run(bus)
    bus.publish("s1", "tool.failed", {"request_id": "r1", "call_id": "c2", "tool": "x"})
    assert got["on_turn_end"] == ["turn.finish"]
    assert got["on_approval"] == ["approval.request", "approval.resolved"]
    assert got["on_error"] == ["tool.failed"]


def test_subagent_spans_nest_under_launching_tool():
    from contextvars import copy_context
    from concurrent.futures import ThreadPoolExecutor
    from jaeger_agent import live
    from jaeger_ai.contract import trace
    from jaeger_ai.core.runtime import subagents

    got: list[tuple[str, dict]] = []

    def child():
        live.emit("subagent.tool.started", {"subagent_id": live.current_subagent(),
                                            "call_id": "kid1", "tool": "read_file"})
        return {"delegated": True, "answer": "x"}

    with live.bind(lambda e, d: got.append((e, d))), live.tool_call("call_parent"):
        with ThreadPoolExecutor(1) as pool:  # copy_context carries emitter + call id
            out = pool.submit(copy_context().run, subagents._reported, "internal", "sub", "t", child).result()
    assert out["answer"] == "x"
    names = [e for e, _ in got]
    assert names == ["subagent.started", "subagent.tool.started", "subagent.finished"]
    sid = got[0][1]["subagent_id"]
    spans = [trace.classify(e, {**d, "turn_id": "r1"}) for e, d in got]
    assert spans[0]["span_id"] == f"agent:{sid}" and spans[0]["parent_span_id"] == "tool:call_parent"
    assert spans[1]["parent_span_id"] == f"agent:{sid}" and spans[1]["kind"] == "tool"
    assert spans[2]["state"] == "succeeded"


def test_live_emit_is_noop_without_host():
    from jaeger_agent import live
    live.emit("tool.progress", {"message": "x"})  # no emitter bound: nothing raises
    assert live.current_tool_call() is None


def test_gateway_tool_events_use_the_loops_real_call_id(tmp_path, monkeypatch):
    from jaeger_agent import live
    from jaeger_ai.core.gateway.server import JaegerGatewayApp, _live_activity_id
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    app = JaegerGatewayApp(store=store)
    store.admit_request("s", "q", request_id="req-1")
    callbacks, flush = app._turn_stream_callbacks("s", "req-1")
    # two concurrent calls of the same tool finish out of order: ids still pair
    with live.tool_call("call_A"):
        callbacks.on_tool_progress("read_file", "start", {"path": "a"})
    with live.tool_call("call_B"):
        callbacks.on_tool_progress("read_file", "start", {"path": "b"})
    with live.tool_call("call_B"):
        callbacks.on_tool_done("read_file", {}, {"ok": True}, True, None, 0.1)
    with live.tool_call("call_A"):
        callbacks.on_tool_done("read_file", {}, {"ok": False}, False, "x", 0.2)
    flush()
    rows = [(e.event, e.data.get("call_id"), e.data.get("ok")) for e in app.event_bus.get_replay_events("s")
            if e.event.startswith("tool.")]
    a, b = _live_activity_id("req-1", "call_A"), _live_activity_id("req-1", "call_B")
    assert ("tool.started", a, None) in rows and ("tool.started", b, None) in rows
    done = {cid: ok for ev, cid, ok in rows if ev != "tool.started"}
    assert done[b] is True and done[a] is False
    assert _live_activity_id("req-2", "call_A") != a  # reused provider ids stay unique per turn


def test_hook_decisions_are_reported_as_nodes_under_the_tool():
    from jaeger_agent import live
    from jaeger_agent.hooks import HookDecision, HookRegistry
    from jaeger_ai.contract import trace
    reg = HookRegistry()
    reg.register("pre_tool", lambda t, a: HookDecision.modify({**a, "safe": True}, "sanitised"), name="sanitiser")
    reg.register("post_tool", lambda t, a, r: {"ok": True, "redacted": True}, name="redactor")
    got = []
    with live.bind(lambda e, d: got.append((e, d))), live.tool_call("c9"):
        d = reg.pre_tool("write_file", {"path": "x", "token": "secret"})
        reg.post_tool("write_file", {}, {"ok": True})
    assert d.action == "modify" and d.hook == "sanitiser"
    assert [x[1]["action"] for x in got] == ["modify", "replace"]
    assert all("secret" not in str(x[1]) for x in got)  # rewritten args never published
    node = trace.classify(*got[0])
    assert node["kind"] == "hook" and node["parent_span_id"] == "tool:c9" and "sanitiser" in node["name"]
    reg.register("pre_tool", lambda t, a: HookDecision.deny("no"), name="guard")
    got.clear()
    with live.bind(lambda e, d: got.append((e, d))), live.tool_call("c10"):
        assert reg.pre_tool("write_file", {}).action == "deny"
    assert trace.classify(*got[0])["state"] == "denied"


def test_plugin_hooks_ride_the_agent_hook_registry(monkeypatch):
    from jaeger_agent import hooks as agent_hooks
    from jaeger_ai.plugins import registry as plugins
    fresh = agent_hooks.HookRegistry()
    monkeypatch.setattr(agent_hooks, "registry", fresh)
    monkeypatch.setattr(plugins, "_AGENT_BRIDGE", [])
    calls = []
    monkeypatch.setattr(plugins, "fire_hook", lambda ev, **kw: calls.append((ev, kw.get("name"))))
    plugins.install_agent_hook_bridge()
    plugins.install_agent_hook_bridge()  # idempotent
    assert fresh.pre_tool("read_file", {}).action == "allow"
    fresh.post_tool("read_file", {}, {"ok": True})
    fresh.fire("on_turn_end", {"event": "turn.finish", "session_id": "s", "data": {"request_id": "r"}})
    assert calls == [("pre_tool", "read_file"), ("post_tool", "read_file"), ("turn_end", None)]
