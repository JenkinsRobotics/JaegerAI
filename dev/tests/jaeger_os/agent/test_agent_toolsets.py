"""Phase-7 toolsets — group definitions + agent-loop filtering.

Toolsets are the Hermes-style mechanism for cutting per-turn context:
the model only sees the schemas for the active toolsets, not every
registered tool. The tests here pin the data model, the resolver's
recursion semantics, and the agent loop's filter wiring.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, Field

from jaeger_os.agent import (
    JAEGER_TOOLSETS,
    JaegerAgent,
    ProviderAdapter,
    clear_registry,
    list_toolsets,
    register_tool,
    resolve_toolsets,
    toolset_for_tool,
)


class _SmallArgs(BaseModel):
    value: str = Field(default="x")


class _StubAdapter(ProviderAdapter):
    name = "stub"

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        # Capture what the loop hands us — we assert on this from tests.
        self.last_tools = list(tools)
        return {"messages": messages, "tools": tools, "system": system}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        return {"role": "assistant", "content": "ok"}

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


# ── data model ─────────────────────────────────────────────────────


def test_every_toolset_has_required_keys():
    """Every entry must carry ``description``, ``tools``, ``includes``
    so the resolver and the ``/toolsets`` panel can rely on the shape."""
    for name, definition in JAEGER_TOOLSETS.items():
        assert "description" in definition, f"{name} missing description"
        assert "tools" in definition, f"{name} missing tools"
        assert "includes" in definition, f"{name} missing includes"
        assert isinstance(definition["tools"], list)
        assert isinstance(definition["includes"], list)


def test_atomic_toolsets_have_no_includes():
    """An atomic toolset (one category, no composition) has no
    ``includes`` — that's the contract :func:`toolset_for_tool` relies
    on to skip composites during reverse lookup."""
    expected_atomic = {
        "time", "math", "host", "files", "web", "memory",
        "memory_umbrella_only", "code", "schedule", "planning",
        "kanban", "browser", "skills",
        "media", "delegate", "comm", "host_ui", "computer",
        "computer_umbrella_only", "toolset_mgmt",
    }
    for name in expected_atomic:
        assert name in JAEGER_TOOLSETS, f"missing atomic toolset: {name}"
        assert JAEGER_TOOLSETS[name]["includes"] == [], (
            f"{name} should be atomic but has includes"
        )


def test_essentials_is_minimal_and_deterministic():
    """The essentials bundle must stay small — it's always-on, so any
    bloat here shows up in EVERY turn's schema."""
    resolved = resolve_toolsets({"essentials"})
    # Reasonable upper bound — if this trips, audit what got added.
    assert len(resolved) < 15, f"essentials grew to {len(resolved)} tools"
    # Core members that must always be in essentials.
    assert "get_time" in resolved
    assert "calculate" in resolved
    assert "system_status" in resolved


def test_default_includes_essentials_plus_typical_chat_tools():
    resolved = resolve_toolsets({"default"})
    # essentials members are present
    assert "get_time" in resolved
    assert "calculate" in resolved
    # plus the typical chat-assistant additions
    assert "read_file" in resolved
    assert "write_file" in resolved
    assert "web_search" in resolved
    assert "memory" in resolved


# ── resolver ───────────────────────────────────────────────────────


def test_resolve_unknown_name_raises_keyerror_with_name():
    with pytest.raises(KeyError, match="nonexistent"):
        resolve_toolsets({"nonexistent"})


def test_resolve_handles_includes_recursively():
    """``developer`` includes ``default`` which includes ``essentials``
    — every leaf tool must surface in the final set."""
    resolved = resolve_toolsets({"developer"})
    # essentials leaf
    assert "calculate" in resolved
    # default leaf
    assert "memory" in resolved
    # developer-only leaf
    assert "execute_code" in resolved


def test_resolve_dedupes_overlapping_toolsets():
    """Two toolsets that share a tool must not double-count."""
    a = resolve_toolsets({"essentials"})
    b = resolve_toolsets({"essentials", "essentials"})
    assert a == b


def test_resolve_star_returns_every_tool():
    """``"*"`` is the convenience alias for every toolset."""
    resolved = resolve_toolsets({"*"})
    # A wide sample of tools across every toolset must appear.
    for sample in ("get_time", "read_file", "web_search", "memory",
                   "execute_code", "computer_use"):
        assert sample in resolved


# ── reverse lookup ─────────────────────────────────────────────────


def test_toolset_for_tool_returns_atomic_owner():
    assert toolset_for_tool("get_time") == "time"
    assert toolset_for_tool("calculate") == "math"
    assert toolset_for_tool("read_file") == "files"
    assert toolset_for_tool("memory") == "memory"


def test_toolset_for_tool_returns_none_for_unknown_tool():
    assert toolset_for_tool("totally_made_up_tool") is None


# ── list_toolsets (the panel surface) ──────────────────────────────


def test_list_toolsets_expands_includes_to_resolved_tools():
    out = list_toolsets()
    assert "default" in out
    # The resolved view shows the union, not just the directly-listed
    # tools (which is empty for composite toolsets).
    default_tools = set(out["default"]["tools"])
    assert "get_time" in default_tools
    assert "read_file" in default_tools


def test_list_toolsets_carries_includes_for_diagnostics():
    """Composites must declare their ``includes`` for /runtime to show
    the dependency graph."""
    out = list_toolsets()
    assert "essentials" in out["default"]["includes"]


# ── JaegerAgent.tools filtering ────────────────────────────────────


def test_agent_with_no_toolset_arg_sees_every_registered_tool():
    @register_tool("a", "tool a", _SmallArgs)
    def _a(value: str = "x") -> dict:
        return {}

    @register_tool("b", "tool b", _SmallArgs)
    def _b(value: str = "x") -> dict:
        return {}

    agent = JaegerAgent(adapter=_StubAdapter())
    assert agent.tool_names() == ["a", "b"]


def test_agent_with_toolset_arg_filters_to_named_tools():
    """The agent constructor honours ``toolsets={...}``: only tools
    that belong to one of the resolved names appear in ``self.tools``."""
    @register_tool("get_time", "", _SmallArgs)
    def _t(value: str = "x") -> dict:
        return {}

    @register_tool("read_file", "", _SmallArgs)
    def _r(value: str = "x") -> dict:
        return {}

    @register_tool("execute_code", "", _SmallArgs)
    def _e(value: str = "x") -> dict:
        return {}

    # essentials => only get_time stays
    agent = JaegerAgent(adapter=_StubAdapter(), toolsets={"essentials"})
    names = set(agent.tool_names())
    assert "get_time" in names
    assert "read_file" not in names
    assert "execute_code" not in names


def test_agent_explicit_tools_arg_wins_over_toolsets():
    """When both ``tools=`` and ``toolsets=`` are given, the explicit
    list takes precedence (the caller knows exactly what they want)."""
    @register_tool("get_time", "", _SmallArgs)
    def _t(value: str = "x") -> dict:
        return {}

    @register_tool("read_file", "", _SmallArgs)
    def _r(value: str = "x") -> dict:
        return {}

    from jaeger_os.agent import get_tool
    only_read = JaegerAgent(
        adapter=_StubAdapter(),
        tools=[get_tool("read_file")],
        toolsets={"essentials"},  # would otherwise yield get_time
    )
    assert only_read.tool_names() == ["read_file"]


def test_agent_records_requested_toolsets_for_diagnostics():
    agent = JaegerAgent(adapter=_StubAdapter(), toolsets=["essentials", "files"])
    assert agent.toolsets == {"essentials", "files"}


def test_agent_tools_arg_alone_leaves_toolsets_empty():
    """When the caller passes ``tools=[...]`` and not ``toolsets=``,
    the diagnostic ``self.toolsets`` reflects the absence — useful so
    the /runtime panel can distinguish "scoped by toolset" from
    "scoped by explicit list"."""
    from jaeger_os.agent import get_tool

    @register_tool("only", "", _SmallArgs)
    def _o(value: str = "x") -> dict:
        return {}

    agent = JaegerAgent(adapter=_StubAdapter(), tools=[get_tool("only")])
    assert agent.toolsets == frozenset()


# ── context savings — what the schema looks like ──────────────────


def test_filtering_drops_schema_size_dramatically():
    """The whole point: filtering to ``essentials`` produces an
    order-of-magnitude smaller tools list than the unfiltered case
    (assuming a realistic tool count). With a 10-tool registry,
    essentials should keep 1-2 tools, not all 10."""
    @register_tool("get_time", "", _SmallArgs)
    def _t(value: str = "x") -> dict:
        return {}

    for n in range(10):
        # Fill the registry with non-essentials tools.
        @register_tool(f"junk_{n}", "", _SmallArgs)
        def _x(value: str = "x") -> dict:  # noqa: B023 — pinned closure name
            return {}

    full = JaegerAgent(adapter=_StubAdapter())
    essentials_only = JaegerAgent(adapter=_StubAdapter(), toolsets={"essentials"})

    assert len(full.tools) == 11
    # essentials includes get_time + a handful of other essentials-tier
    # tools, but none of the junk_N — so we expect 1 here (only
    # get_time was registered with an essentials-matching name).
    assert len(essentials_only.tools) == 1
    assert essentials_only.tools[0].name == "get_time"
