"""Standalone integration tests for jaeger-loop wiring models, tools, authority, memory, reliability & events."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from jaeger_authority import PolicyEngine, UnconfinedSandbox
from jaeger_contracts import ExecutionLoopPort, ToolResult
from jaeger_events import EventBus
from jaeger_loop import AgentLoop, TurnVerdict
from jaeger_memory import SqliteStateMemory
from jaeger_models import ReplayModel
from jaeger_reliability import ReliabilityEngine
from jaeger_tools import ToolRegistry, ToolSpec


def test_agent_loop_parallel_reads_arg_repair_policy_and_checkpoints(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    mem = SqliteStateMemory(tmp_path / "state")
    rel = ReliabilityEngine(repeat_threshold=3)
    tools = ToolRegistry(workspace=ws, policy=PolicyEngine(), sandbox=UnconfinedSandbox())

    active_reads = [0]
    max_concurrent = [0]
    lock = threading.Lock()

    def slow_read(args):
        with lock:
            active_reads[0] += 1
            max_concurrent[0] = max(max_concurrent[0], active_reads[0])
        time.sleep(0.03)
        with lock:
            active_reads[0] -= 1
        return ToolResult("read_num", True, f"val={args['n']}")

    tools.register(ToolSpec(
        name="read_num",
        description="Read a number.",
        schema={"properties": {"n": {"type": "integer"}}},
        handler=slow_read,
        tier="read_only",
        read_only=True,
    ))
    tools.register_shell_tool()

    # Step 1: two concurrent read_only calls (with stringified int repaired by ReliabilityEngine!)
    # Step 2: safe shell echo inside workspace (zero-nag ALLOW)
    # Step 3: final answer
    model = ReplayModel([
        {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "read_num", "arguments": "{'n': '1'}"},
                {"id": "c2", "name": "read_num", "arguments": "{'n': '2'}"},
            ],
        },
        {
            "content": "",
            "tool_calls": [{"id": "c3", "name": "shell", "arguments": {"command": "echo DONE"}}],
        },
        {"content": "All engineering checks passed."},
    ])

    loop = AgentLoop(model=model, tools=tools, memory=mem, reliability=rel, events=bus, session_id="s-eng")
    assert isinstance(loop, ExecutionLoopPort)

    out = loop.run_turn("Inspect and build")
    assert out["verdict"] == TurnVerdict.COMPLETE.value
    assert out["steps"] == 3
    assert out["content"] == "All engineering checks passed."
    assert out["checkpoint_id"] is not None
    assert max_concurrent[0] >= 2  # verified parallel execution of read_only batch!
    assert "turn.complete" in seen_events


def test_agent_loop_halts_on_stuck_repetition(tmp_path: Path) -> None:
    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    tools.register_shell_tool()

    repeated = {"content": "", "tool_calls": [{"id": "x", "name": "shell", "arguments": {"command": "echo hi"}}]}
    model = ReplayModel([repeated, repeated, repeated, repeated])
    loop = AgentLoop(model=model, tools=tools, reliability=ReliabilityEngine(repeat_threshold=3))

    out = loop.run_turn("Do task", max_steps=10)
    assert out["verdict"] == TurnVerdict.LOOP_HALTED.value
    assert out["steps"] == 3


def test_slice6_state_machine_capability_ordering_mailbox_two_tier_and_cancel_scope(tmp_path: Path) -> None:
    from jaeger_loop import (
        CancelScope,
        CapabilityOrdering,
        LoopOperation,
        LoopState,
        LoopStateMachine,
        MailPriority,
        TurnMailbox,
        TwoTierLoopDetector,
        instantiate_middlewares_for_run,
    )

    # 1. Goose state machine operations & effects
    sm = LoopStateMachine()
    eff1 = sm.apply(LoopOperation.START_TURN, {"prompt": "hi"})
    assert sm.state == LoopState.CALLING_MODEL and eff1[0].kind == "invoke_model"
    eff2 = sm.apply(LoopOperation.APPROVAL_REQUIRED, {"tool": "shell"})
    assert sm.state == LoopState.AWAITING_APPROVAL
    assert [e.kind for e in eff2] == ["checkpoint", "request_approval"]
    sm.apply(LoopOperation.APPROVAL_GRANTED)
    assert sm.state == LoopState.EXECUTING_TOOLS
    sm.apply(LoopOperation.MODEL_TEXT_ONLY)
    assert sm.state == LoopState.COMPLETED

    # 2. Pydantic-AI CapabilityOrdering + for_run isolation
    class _MW:
        def __init__(self, name: str, ordering: CapabilityOrdering):
            self.name = name
            self.capability_ordering = ordering
            self.run_id = None

        def for_run(self, run_id: str):
            clone = _MW(self.name, self.capability_ordering)
            clone.run_id = run_id
            return clone

    mw_b = _MW("audit", CapabilityOrdering("audit", priority=50, after=("auth",)))
    mw_a = _MW("auth", CapabilityOrdering("auth", priority=100))
    mw_c = _MW("telemetry", CapabilityOrdering("telemetry", priority=10, before=("auth",)))
    ordered = instantiate_middlewares_for_run([mw_b, mw_a, mw_c], "run-42")
    assert [m.name for m in ordered] == ["telemetry", "auth", "audit"]
    assert all(m.run_id == "run-42" for m in ordered)
    assert mw_a.run_id is None  # parent template unmutated

    # 3. Codex TurnMailbox priority (ABORT > STEER > NORMAL)
    box = TurnMailbox()
    box.post("normal note", priority=MailPriority.NORMAL)
    box.steer("change direction")
    box.abort("stop now")
    drained = box.drain()
    assert [m.priority for m in drained] == [MailPriority.ABORT, MailPriority.STEER, MailPriority.NORMAL]

    # 4. Gemini CLI 2-tier oscillation detector (A -> B -> A -> B -> A -> B)
    det = TwoTierLoopDetector(max_identical=10, oscillation_repeats=3)
    halt = None
    for i in range(6):
        tool = "read_a" if i % 2 == 0 else "read_b"
        halt = det.record(tool, {"x": i % 2}, {"ok": True})
    assert halt is not None and "oscillation" in halt

    # 5. Isolated sub-agent CancelScope tree
    parent = CancelScope()
    child_a = parent.child()
    child_b = parent.child()
    child_a.cancel("subagent timeout")
    assert child_a.is_cancelled and not parent.is_cancelled and not child_b.is_cancelled
    parent.cancel("user stop")
    assert parent.is_cancelled and child_b.is_cancelled



def test_budget_exhaustion_reports_last_tool_result_without_granting_more_tools(tmp_path: Path) -> None:
    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    tools.register_shell_tool()

    class BudgetModel:
        name = "budget-test"
        calls = 0

        def complete(self, messages, *, tools):
            self.calls += 1
            if self.calls == 1:
                assert tools
                return {"tool_calls": [{"id": "last", "name": "shell", "arguments": {"command": "echo VERIFIED"}}]}
            assert tools == []
            assert messages[-2]["role"] == "tool"
            assert "VERIFIED" in messages[-2]["content"]
            return {"content": "Verified output. More work remains."}

    model = BudgetModel()
    result = AgentLoop(model=model, tools=tools).run_turn("Check output", max_steps=1)
    assert model.calls == 2
    assert result["steps"] == 1
    assert result["verdict"] == TurnVerdict.BUDGET_EXHAUSTED.value
    assert result["content"] == "Verified output. More work remains."


class _TinyWindowModel(ReplayModel):
    """ReplayModel whose profile reports a tiny context window (1000 tokens)."""

    def profile(self, model_id: str | None = None):
        from jaeger_contracts import ModelProfile
        return ModelProfile(model_id=model_id or "tiny", provider="test", context_window=1000)


def test_agent_loop_extra_slice_resumes_without_replaying_tool(tmp_path: Path) -> None:
    """max_steps=1 + extra_slices=1: slice 1 runs one tool and yields; slice 2 resumes
    from the same transcript (tool result already present, tool NOT re-executed),
    emits exactly one turn.continued, and reaches COMPLETE."""
    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    executions = [0]

    def probe(args):
        executions[0] += 1
        return ToolResult("probe", True, "probe-ok")

    tools.register(ToolSpec(
        name="probe",
        description="Harmless probe.",
        schema={"properties": {}},
        handler=probe,
        tier="read_only",
        read_only=True,
    ))

    model = ReplayModel([
        {"content": "", "tool_calls": [{"id": "t1", "name": "probe", "arguments": {}}]},
        {"content": "Final answer."},
    ])
    loop = AgentLoop(model=model, tools=tools, events=bus, session_id="s-slice")
    out = loop.run_turn("Do it", max_steps=1, extra_slices=1)

    assert out["verdict"] == TurnVerdict.COMPLETE.value
    assert out["content"] == "Final answer."
    assert out["steps"] == 2
    assert executions[0] == 1  # tool executed exactly once across both slices
    assert seen_events.count("turn.continued") == 1
    assert seen_events.index("turn.continued") < seen_events.index("turn.complete")
    # Transcript carries the tool result into the second slice; no duplicate tool call.
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 1 and "probe-ok" in tool_msgs[0]["content"]


def test_agent_loop_extra_slice_blocked_by_pre_slice_guard(tmp_path: Path) -> None:
    """pre_slice_guard returning True at the slice boundary halts before the next
    model step with LOOP_HALTED and no turn.continued."""
    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    tools.register(ToolSpec(
        name="probe",
        description="Harmless probe.",
        schema={"properties": {}},
        handler=lambda args: ToolResult("probe", True, "ok"),
        tier="read_only",
        read_only=True,
    ))
    model = ReplayModel([
        {"content": "", "tool_calls": [{"id": "t1", "name": "probe", "arguments": {}}]},
        {"content": "should never be reached"},
    ])
    loop = AgentLoop(model=model, tools=tools, events=bus, session_id="s-estop")
    out = loop.run_turn("Do it", max_steps=1, extra_slices=1, pre_slice_guard=lambda: True)

    assert out["verdict"] == TurnVerdict.LOOP_HALTED.value
    assert out["steps"] == 1
    assert "turn.continued" not in seen_events
    assert "turn.estop_halted" in seen_events
    assert len(model.calls) == 1  # second slice never invoked the model


def test_agent_loop_compacts_at_80pct_of_model_context_window(tmp_path: Path) -> None:
    """History sized to ~85% of a 1000-token window must trigger percentage compaction
    (digest pinned, recent turns verbatim) before the first model call."""
    from jaeger_memory.compactor import DIGEST_TAG

    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    model = _TinyWindowModel([{"content": "done"}])

    # ~850 tokens of history (3 chars/token heuristic) + system prompt -> >= 80% of 1000.
    filler = "x" * 3000
    history = [
        {"role": "user", "content": "old task"},
        {"role": "assistant", "content": "working on it"},
        {"role": "tool", "name": "shell", "content": filler},
        {"role": "user", "content": "next task"},
        {"role": "assistant", "content": "ok"},
    ]
    loop = AgentLoop(model=model, tools=tools, events=bus, session_id="s-compact")
    out = loop.run_turn("continue", history=history)

    assert out["verdict"] == TurnVerdict.COMPLETE.value
    assert "context.compacted" in seen_events
    # The model received a compacted message list containing the digest and the recent turn.
    sent_msgs = model.calls[0]["messages"]
    assert any(DIGEST_TAG in str(m.get("content") or "") for m in sent_msgs)
    assert sent_msgs[-1]["role"] == "user" and sent_msgs[-1]["content"] == "continue"
    assert len(sent_msgs) < len(history) + 2  # compaction actually shrank the list


def test_agent_loop_no_compaction_below_threshold(tmp_path: Path) -> None:
    """Small history under the 80% threshold must pass through untouched (no digest)."""
    from jaeger_memory.compactor import DIGEST_TAG

    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    model = _TinyWindowModel([{"content": "done"}])
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    loop = AgentLoop(model=model, tools=tools, events=bus, session_id="s-small")
    out = loop.run_turn("again", history=history)

    assert out["verdict"] == TurnVerdict.COMPLETE.value
    assert "context.compacted" not in seen_events
    assert not any(DIGEST_TAG in str(m.get("content") or "") for m in out["messages"])


def test_agent_loop_recovers_from_empty_final_response(tmp_path: Path) -> None:
    """An empty final model response must trigger one tool-free recovery pass rather than saving ''."""
    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    tools.register(ToolSpec(
        name="probe",
        description="Harmless probe.",
        schema={"properties": {}},
        handler=lambda _args: ToolResult("probe", True, "probe-data"),
        tier="read_only",
        read_only=True,
    ))
    model = ReplayModel([
        {"content": "", "tool_calls": [{"id": "t1", "name": "probe", "arguments": {}}]},
        {"content": "   "},
        {"content": "Recovered answer from probe-data."},
    ])
    loop = AgentLoop(model=model, tools=tools, events=bus, session_id="s-empty")
    out = loop.run_turn("Summarize probe")

    assert out["verdict"] == TurnVerdict.COMPLETE.value
    assert out["content"] == "Recovered answer from probe-data."
    assert "turn.empty_recovery" in seen_events
    assert len(model.calls) == 3
    assert "Summarize probe" in model.calls[-1]["messages"][-1]["content"]


def test_agent_loop_resolves_tool_alias_and_nudges_read_stall(tmp_path: Path) -> None:
    """Tool aliases (e.g. bash -> shell) execute cleanly, and 8+ read/fetch calls trigger a strategy shift."""
    bus = EventBus()
    seen_events: list[str] = []
    bus.subscribe("*", lambda ev: seen_events.append(ev.event_type))

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    tools.register_shell_tool()
    tools.register(ToolSpec(
        name="web_fetch",
        description="Stub fetch.",
        schema={"properties": {"url": {"type": "string"}}},
        handler=lambda args: ToolResult("web_fetch", True, f"fetched:{args.get('url')}"),
        tier="read_only",
        read_only=True,
    ))

    # Step 1 calls 'bash' (aliased to 'shell'), Steps 2..9 do 8 web_fetch calls, Step 10 answers.
    turns = [
        {"content": "", "tool_calls": [{"id": "c0", "name": "bash", "arguments": {"command": "echo ALIAS_OK"}}]},
        *[
            {"content": "", "tool_calls": [{"id": f"f{i}", "name": "web_fetch", "arguments": {"url": f"https://example.test/{i}"}}]}
            for i in range(8)
        ],
        {"content": "Synthesized answer."},
    ]
    model = ReplayModel(turns)
    rel = ReliabilityEngine(repeat_threshold=4, tool_aliases={"bash": "shell"})
    loop = AgentLoop(model=model, tools=tools, reliability=rel, events=bus, session_id="s-alias")
    out = loop.run_turn("Check and synthesize", max_steps=12)

    assert out["verdict"] == TurnVerdict.COMPLETE.value
    assert out["content"] == "Synthesized answer."
    tool_msgs = [m for m in out["messages"] if m.get("role") == "tool"]
    assert any(m.get("name") == "shell" and "ALIAS_OK" in m.get("content", "") for m in tool_msgs)
    assert "turn.strategy_shift" in seen_events
