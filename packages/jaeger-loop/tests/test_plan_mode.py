"""Tests for OpenCode-style dual execution modes (build vs plan) in jaeger-loop."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_authority import PolicyEngine, UnconfinedSandbox
from jaeger_contracts import ToolResult
from jaeger_events import EventBus
from jaeger_loop import AgentLoop, AgentMode, PlanModeMiddleware
from jaeger_memory import SqliteStateMemory
from jaeger_models import ReplayModel
from jaeger_reliability import ReliabilityEngine
from jaeger_tools import ToolRegistry, ToolSpec


def test_plan_mode_blocks_mutating_tools_and_allows_reads(tmp_path: Path) -> None:
    assert AgentMode.parse("plan") == AgentMode.PLAN
    assert AgentMode.parse("build") == AgentMode.BUILD
    with pytest.raises(ValueError):
        AgentMode.parse("yolo")

    tools = ToolRegistry(workspace=tmp_path, policy=PolicyEngine(), sandbox=UnconfinedSandbox())
    mutated = [False]
    tools.register(
        ToolSpec(
            name="read_status",
            description="Read status",
            schema={"type": "object", "properties": {}},
            handler=lambda _args: ToolResult(tool_name="read_status", ok=True, output='{"status":"nominal"}'),
            read_only=True,
        )
    )
    tools.register(
        ToolSpec(
            name="write_config",
            description="Write config",
            schema={"type": "object", "properties": {}},
            handler=lambda _args: (mutated.__setitem__(0, True) or ToolResult(tool_name="write_config", ok=True, output='{"written":true}')),
            read_only=False,
        )
    )

    current_mode = [AgentMode.PLAN]
    mw = PlanModeMiddleware(
        is_read_only=tools.is_read_only,
        mode_getter=lambda: current_mode[0],
    )
    model = ReplayModel([
        {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "read_status", "arguments": {}},
                {"id": "c2", "name": "write_config", "arguments": {}},
            ],
        },
        {"content": "Planned safely without writing."},
    ])
    loop = AgentLoop(
        model=model,
        tools=tools,
        memory=SqliteStateMemory(tmp_path / "mem"),
        reliability=ReliabilityEngine(),
        events=EventBus(),
        middlewares=[mw],
        session_id="plan-test",
    )
    res = loop.run_turn("Inspect and propose config change")
    assert res["verdict"] == "complete"
    assert mutated[0] is False
    # Read tool succeeded, write tool was blocked by PlanModeMiddleware
    tool_msgs = [m for m in res["messages"] if m.get("role") == "tool"]
    assert any("nominal" in str(m.get("content") or "") for m in tool_msgs)
    assert any("Blocked in PLAN mode" in str(m.get("content") or "") for m in tool_msgs)

    # Switching to BUILD mode allows the mutating tool cleanly
    current_mode[0] = AgentMode.BUILD
    model2 = ReplayModel([
        {"content": "", "tool_calls": [{"id": "c3", "name": "write_config", "arguments": {}}]},
        {"content": "Config written."},
    ])
    loop2 = AgentLoop(
        model=model2,
        tools=tools,
        memory=SqliteStateMemory(tmp_path / "mem2"),
        reliability=ReliabilityEngine(),
        events=EventBus(),
        middlewares=[mw],
        session_id="build-test",
    )
    res2 = loop2.run_turn("Apply config")
    assert res2["verdict"] == "complete"
    assert mutated[0] is True
