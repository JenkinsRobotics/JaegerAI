"""Architectural Boundary and Dependency Inversion Tests (Workstream 20)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


def test_jaeger_agent_has_no_upward_usage_stats_imports():
    """Verify that jaeger_agent loop core does not directly import jaeger_ai usage_stats."""
    agent_file = Path("packages/jaeger-agent/jaeger_agent/loop/jaeger_agent.py")
    assert agent_file.is_file()

    tree = ast.parse(agent_file.read_text(encoding="utf-8"))
    upward_imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "jaeger_ai.core.runtime.usage_stats" in module:
                upward_imports.append((node.lineno, module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "jaeger_ai.core.runtime.usage_stats" in alias.name:
                    upward_imports.append((node.lineno, alias.name))

    assert upward_imports == [], (
        f"Found illegal upward imports in jaeger_agent.py: {upward_imports}. "
        "Use dependency inversion via AgentCallbacks instead!"
    )


def test_agent_callbacks_telemetry_inversion():
    """Verify that AgentCallbacks properly exposes usage telemetry hooks."""
    from jaeger_agent.loop.callbacks import AgentCallbacks

    cb = AgentCallbacks()
    assert hasattr(cb, "record_skill_route")
    assert hasattr(cb, "record_skill")
    assert hasattr(cb, "record_skill_outcome")
    assert hasattr(cb, "record_model_usage")
    assert hasattr(cb, "record_tool")

    # Safe invocation without callbacks does not raise
    cb.on_record_skill_route("test_skill", "heuristic")
    cb.on_record_skill("test_skill")
    cb.on_record_skill_outcome("test_skill", outcome="smooth")
    cb.on_record_model_usage("ollama", "kimi-k2.7-code:cloud", prompt_tokens=100, cached_prompt_tokens=20, completion_tokens=50)
    cb.on_record_tool("git_status", ok=True, elapsed=0.01)

    # Invocation with injected callback functions
    recorded = []
    cb.record_tool = lambda name, ok=True, elapsed=0.0: recorded.append((name, ok, elapsed))
    cb.on_record_tool("test_tool", ok=True, elapsed=0.05)
    assert recorded == [("test_tool", True, 0.05)]
