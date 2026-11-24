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
