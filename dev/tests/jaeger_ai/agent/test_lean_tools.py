"""Lean tool surface — the model sees CORE + a catalog, not all 70 schemas.

This is the test net for the architectural change that flipped JROS from
sending all tool schemas every turn (~25K tokens of overhead) to a
catalog-plus-on-demand-describe pattern (~3K tokens).

Pinned here:
  - The agent's ``tools`` property re-evaluates ``tool_visible`` every
    access, so a mid-session ``load_tools`` widens the view on the
    very next turn.
  - The agent's ``all_tools`` keeps the FULL registered set so the
    loop can still validate + dispatch a call whose schema the model
    learned via ``describe_tool``.
  - The ``describe_tool`` meta-tool returns the schema of any registered
    tool — including ones currently hidden from the model.
  - ``load_tools`` + ``describe_tool`` both live in CORE so they're
    reachable from any session, scoped or not.
"""

from __future__ import annotations

import pytest

from jaeger_ai.agent.loop.jaeger_agent import JaegerAgent
from jaeger_os.core.tools.tool_registry import (
    get_tool, get_tools, register_tool_from_function, unregister_tool,
)
from jaeger_ai.agent.skill_registry import toolset_scoping as ts


@pytest.fixture
def stub_tools():
    """Register two stub tools — one CORE-visible (``stub_core``), one
    bound to the ``code`` toolset (``stub_hidden``) — so the lean-filter
    tests have something stable to look at regardless of which other
    modules happened to import. Other tests in this suite call
    ``clear_registry`` which wipes ``describe_tool`` too; re-register
    it here so the meta-tool is reachable in any test ordering."""
    from jaeger_os.core.tools.tool_registry import has_tool
    from jaeger_ai.agent.tools.meta import describe_tool as _desc

    if not has_tool("describe_tool"):
        register_tool_from_function(_desc)

    @register_tool_from_function
    def stub_core(arg: str = "x") -> dict:
        """A test-only tool that lives in CORE."""
        return {"got": arg}

    @register_tool_from_function
    def stub_hidden(arg: str = "x") -> dict:
        """A test-only tool that lives only in the ``code`` toolset
        and is hidden by the lean filter until that toolset loads."""
        return {"got": arg}

    # Hand-place them on the visibility map for the test.
    original_core = ts.CORE
    ts.CORE = frozenset(set(original_core) | {"stub_core"})
    original_code = ts.TOOLSETS.get("code")
    ts.TOOLSETS["code"] = frozenset(set(original_code or frozenset()) | {"stub_hidden"})
    try:
        yield
    finally:
        unregister_tool("stub_core")
        unregister_tool("stub_hidden")
        ts.CORE = original_core
        if original_code is not None:
            ts.TOOLSETS["code"] = original_code
        else:
            ts.TOOLSETS.pop("code", None)


# ── visibility filter wired into the agent ─────────────────────────


def _make_agent_no_filter():
    """Build a JaegerAgent with no adapter calls; we only inspect
    ``tools`` and ``all_tools`` so a stub adapter is enough. The
    ``ProviderAdapter`` ABC requires implementations of describe/
    format/call/parse, so use a minimal subclass."""
    from jaeger_ai.agent.adapters.base import ProviderAdapter

    class _StubAdapter(ProviderAdapter):
        def describe(self): return "stub"
        def format_messages(self, *_a, **_kw): return ()
        def call(self, *_a, **_kw): return None
        def parse_response(self, *_a, **_kw): return {"role": "assistant"}
        def supports(self, *_a, **_kw): return False

    return JaegerAgent(adapter=_StubAdapter())


def test_agent_tools_is_filtered_by_tool_visible(monkeypatch, stub_tools):
    """With scoping on (the default), the agent's visible tools is a
    proper subset of all_tools — the hidden ones still exist in the
    registry for dispatch + describe_tool lookup."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    ts.reset_toolsets()
    agent = _make_agent_no_filter()

    visible_names = {t.name for t in agent.tools}
    all_names = {t.name for t in agent.all_tools}

    # CORE-tagged stub is visible; toolset-tagged stub is hidden.
    assert "stub_core" in visible_names
    assert "stub_hidden" not in visible_names
    assert "stub_hidden" in all_names, "hidden tool must still exist for dispatch"
    # describe_tool is in CORE so the model can always reach it.
    assert "describe_tool" in visible_names


def test_full_tools_env_var_disables_the_filter(monkeypatch):
    """``JAEGER_FULL_TOOLS=1`` makes ``tools == all_tools`` again, the
    bench-harness compatibility mode."""
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    ts.reset_toolsets()
    agent = _make_agent_no_filter()
    assert {t.name for t in agent.tools} == {t.name for t in agent.all_tools}


def test_load_toolset_widens_view_on_the_next_access(monkeypatch, stub_tools):
    """The point of the ``tools`` property: a load_tools call DURING
    a turn must reach the next call to ``tools`` without an agent
    rebuild. That's what makes the catalog-then-load pattern usable."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    ts.reset_toolsets()
    agent = _make_agent_no_filter()

    before = {t.name for t in agent.tools}
    assert "stub_hidden" not in before, "stub_hidden should start hidden"

    # Simulate the load_tools tool firing.
    assert ts.enable_toolset("code") is True

    after = {t.name for t in agent.tools}
    assert "stub_hidden" in after, "loading 'code' should expose stub_hidden"
    # The visible set strictly grows; nothing in the old set gets dropped.
    assert before <= after


def test_explicit_tools_list_bypasses_the_filter(monkeypatch):
    """When a caller passes ``tools=[...]`` explicitly, they get back
    exactly that list — the filter is for the default/toolsets paths."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    from jaeger_ai.agent.adapters.base import ProviderAdapter

    class _StubAdapter(ProviderAdapter):
        def describe(self): return "stub"
        def format_messages(self, *_a, **_kw): return ()
        def call(self, *_a, **_kw): return None
        def parse_response(self, *_a, **_kw): return {"role": "assistant"}
        def supports(self, *_a, **_kw): return False

    # Pick a non-CORE tool; if the filter were applied, it'd vanish.
    explicit = [t for t in get_tools() if t.name == "run_python"]
    if not explicit:
        # run_python may register under a different name in some configs;
        # just pick any tool not in CORE to make the point.
        explicit = [t for t in get_tools() if t.name not in ts.CORE][:1]
    agent = JaegerAgent(adapter=_StubAdapter(), tools=explicit)
    assert [t.name for t in agent.tools] == [t.name for t in explicit]


# ── describe_tool meta-tool ────────────────────────────────────────


def test_describe_tool_returns_schema_for_a_visible_tool(stub_tools):
    """Sanity check — describe_tool works for tools the model already
    sees, so the model can introspect its own toolbox."""
    tool = get_tool("describe_tool")
    out = tool.dispatch({"name": "stub_core"})
    assert out["ok"] is True
    assert out["name"] == "stub_core"
    assert isinstance(out["parameters"], dict)
    # Description text comes from the function's docstring.
    assert out["description"]


def test_describe_tool_returns_schema_for_a_hidden_tool(stub_tools):
    """The whole point — model can peek at a tool that's NOT in its
    current visible set, without loading a whole category first."""
    tool = get_tool("describe_tool")
    out = tool.dispatch({"name": "stub_hidden"})
    assert out["ok"] is True
    assert out["name"] == "stub_hidden"
    # The schema describes the args the model would pass.
    params = out["parameters"]
    assert "properties" in params or "type" in params


def test_describe_tool_handles_unknown_name(stub_tools):
    tool = get_tool("describe_tool")
    out = tool.dispatch({"name": "totally_nonexistent_tool"})
    assert out["ok"] is False
    assert "unknown" in out["error"].lower()


def test_describe_tool_handles_empty_name(stub_tools):
    tool = get_tool("describe_tool")
    out = tool.dispatch({"name": "   "})
    assert out["ok"] is False
