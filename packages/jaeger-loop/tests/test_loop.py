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

