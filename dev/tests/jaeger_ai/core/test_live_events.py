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
