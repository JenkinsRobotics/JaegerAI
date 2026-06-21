from __future__ import annotations

import pytest

from jaeger_os.agent import clear_registry, has_tool
from jaeger_os.agent.skill_registry.skill_loader import _ToolCapturingAgent


class _FakeAgent:
    """Legacy pydantic-ai stand-in; only used for attribute pass-through
    now (skills that read ``agent.model``, etc.). The capturing wrapper
    no longer forwards tool registrations to it."""


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def test_tool_capture_handles_bare_tool_plain() -> None:
    """The bare ``@agent.tool_plain`` form (no kwargs) lifts the function
    into the framework-free registry AND records it in the capturing
    wrapper's ``captured`` list (so the skill becomes its own toolset)."""
    capturing = _ToolCapturingAgent(_FakeAgent())

    @capturing.tool_plain
    def demo_tool() -> dict:
        """Demo tool."""
        return {"ok": True}

    assert demo_tool() == {"ok": True}
    assert capturing.captured == ["demo_tool"]
    assert has_tool("demo_tool")


def test_tool_capture_handles_parameterized_tool_plain() -> None:
    """The ``@agent.tool_plain(retries=1)`` form still captures the
    function name. Legacy kwargs the new path doesn't understand
    (``retries``) are silently dropped — the new agent loop owns retry
    semantics now."""
    capturing = _ToolCapturingAgent(_FakeAgent())

    @capturing.tool_plain(retries=1)
    def demo_tool() -> dict:
        """Demo tool."""
        return {"ok": True}

    assert demo_tool() == {"ok": True}
    assert capturing.captured == ["demo_tool"]
    assert has_tool("demo_tool")


def test_tool_capture_honours_name_override() -> None:
    """Skills that rename a tool via ``@agent.tool_plain(name=...)`` get
    the renamed registration."""
    capturing = _ToolCapturingAgent(_FakeAgent())

    @capturing.tool_plain(name="custom_alias")
    def underlying_fn() -> dict:
        """Custom-named tool."""
        return {"ok": True}

    assert has_tool("custom_alias")
    assert not has_tool("underlying_fn")
