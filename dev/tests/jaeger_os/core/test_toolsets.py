"""Toolset scoping — the model sees a small CORE set and loads the rest
on demand, so it never routes over all ~60 tools at once. A skill is its
own self-describing toolset.
"""

from __future__ import annotations

import pytest

from jaeger_os.agent.skill_registry import toolset_scoping as ts


@pytest.fixture(autouse=True)
def _clean_toolset_state(monkeypatch):
    """Toolset state is module-global — isolate each test. These tests
    exercise the scoping LOGIC, so enable it (it is opt-in by default)."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    ts.reset_toolsets()
    ts._SKILL_TOOLSETS.clear()
    ts._SKILL_SUMMARY.clear()
    yield
    ts.reset_toolsets()
    ts._SKILL_TOOLSETS.clear()
    ts._SKILL_SUMMARY.clear()


def test_scoping_off_by_default_shows_everything(monkeypatch) -> None:
    """With scoping disabled (the default — reverted after Gemma 4
    routing regressed from 100% to 67.6% under naive scoping), every
    tool is visible. Opt into the lean surface via
    ``JAEGER_TOOLSET_SCOPING=1`` when context is tight."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    ts.reset_toolsets()
    assert ts.tool_visible("get_time")
    assert ts.tool_visible("execute_code")       # would be hidden if scoped
    assert ts.tool_visible("schedule_prompt")
    assert ts.tool_visible("anything_at_all")


def test_scoping_on_via_env_hides_categorised_tools(monkeypatch) -> None:
    """``JAEGER_TOOLSET_SCOPING=1`` enables the lean surface — useful
    for context-tight runs, accepts the routing regression on some
    models in exchange for prompt-prefix savings.

    Probe is ``terminal`` (in the ``code`` toolset since the
    visibility refactor moved ``execute_code`` into CORE)."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    ts.reset_toolsets()
    assert ts.tool_visible("get_time")        # CORE
    assert not ts.tool_visible("terminal")    # in the ``code`` toolset → hidden
    assert ts.tool_visible("anything_at_all")  # fail-open for unclassified


def test_full_tools_env_overrides_explicit_scoping(monkeypatch) -> None:
    """``JAEGER_FULL_TOOLS=1`` wins even when scoping is asked for —
    a kill-switch for bench harnesses + debug."""
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    assert ts.tool_visible("terminal")
    assert ts.tool_visible("schedule_prompt")


# ── core + built-in classes ─────────────────────────────────────────


def test_core_tools_always_visible() -> None:
    """CORE was slimmed: the umbrella ``memory`` replaced the five
    granular memory tools, and ``execute_code`` was promoted from
    the ``code`` toolset. Pin the new membership."""
    for name in ("get_time", "memory", "web_search", "todo",
                 "execute_code", "kanban", "skill", "load_tools"):
        assert ts.tool_visible(name), name


def test_non_core_tool_hidden_until_its_toolset_loads() -> None:
    """``terminal`` is in the ``code`` toolset (``execute_code`` moved
    to CORE) — hidden by default, visible after load."""
    assert not ts.tool_visible("terminal")
    assert ts.enable_toolset("code") is True
    assert ts.tool_visible("terminal")


def test_loading_one_toolset_does_not_reveal_another() -> None:
    ts.enable_toolset("code")
    assert ts.tool_visible("terminal")              # code — loaded
    assert not ts.tool_visible("schedule_prompt")  # scheduling — not loaded


def test_unknown_toolset_is_rejected() -> None:
    assert ts.enable_toolset("nonexistent") is False


def test_uncategorised_tool_fails_open() -> None:
    """A tool in no toolset at all is never silently hidden."""
    assert ts.tool_visible("a_brand_new_uncategorised_tool")


def test_reset_returns_to_core_only() -> None:
    ts.enable_toolset("code")
    ts.reset_toolsets()
    assert not ts.tool_visible("terminal")


def test_active_toolset_names_always_includes_core() -> None:
    assert "core" in ts.active_toolset_names()
    ts.enable_toolset("code")
    assert ts.active_toolset_names() == {"core", "code"}


# ── skills as self-describing toolsets ──────────────────────────────


def test_skill_registers_as_its_own_toolset() -> None:
    ts.register_skill_toolset("computer", ["computer_do", "computer_click"],
                              summary="drive macOS apps")
    assert not ts.tool_visible("computer_do")     # skill toolset not loaded
    assert ts.enable_toolset("computer") is True
    assert ts.tool_visible("computer_do")
    assert ts.tool_visible("computer_click")


def test_catalog_lists_built_ins_and_skills() -> None:
    ts.register_skill_toolset("computer", ["computer_do"],
                              summary="drive macOS apps")
    cat = ts.all_toolsets()
    assert "code" in cat and "files" in cat        # built-in classes
    assert cat["computer"] == "drive macOS apps"   # skill toolset


# ── classification integrity ────────────────────────────────────────


# Tools that are intentionally NOT in any toolset — they're either
# meta-tools (callable from anywhere), umbrella consolidations that
# subsume a category, or one-offs we never wanted to group. Anything
# not in CORE, not in a TOOLSETS bucket, AND not on this list should
# fail the integrity test below — that catches future renames that
# silently leave a tool fail-open instead of intentionally classified.
_INTENTIONAL_FAIL_OPEN: frozenset[str] = frozenset({
    # Meta-introspection — always reachable.
    "describe_tool", "load_tools",
    # Umbrellas — they SUBSUME categories so by design they're outside
    # any single one.
    "memory", "kanban", "skill", "computer_use", "computer_do", "browser",
    # Self-update is always available — the agent rewrites its own
    # identity / soul.
    "set_name", "update_soul",
    # Scheduling — list_schedules is a read-only listing alongside the
    # gated schedule_prompt / cancel_schedule. The triplet stays as one
    # group; ``list_schedules`` is in the "scheduling" set elsewhere
    # but if the loader spots it un-classified, that's OK.
})


def test_every_registered_tool_is_classified_or_explicit_fail_open(monkeypatch) -> None:
    """Defensive: every built-in tool must either be in CORE, in a
    declared TOOLSETS bucket, or on the explicit fail-open allowlist.
    Without this test, a future tool rename (e.g. the run_python →
    execute_code rename that motivated this test) leaves the renamed
    tool fail-open + un-classified — the scoping default looked OK
    because fail-open masked the drift.

    The rule is: every tool must be DELIBERATELY classified."""
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)

    # Trigger module-level tool registration. main.py's @register_tool_from_function
    # block only fires inside the agent-build closure, so we load enough
    # to cover the always-on path — and assert only against what's
    # available.
    from jaeger_os.agent.schemas.tool_registry import get_tools  # noqa
    import jaeger_os.agent.tools  # noqa — pulls module-level registrations

    all_classified: set[str] = set(ts.CORE)
    for members in ts.TOOLSETS.values():
        all_classified.update(members)

    unclassified: list[str] = []
    for tool in get_tools():
        if tool.name in all_classified:
            continue
        if tool.name in _INTENTIONAL_FAIL_OPEN:
            continue
        # Skip test-stub tools that other suites register via
        # ``register_tool_from_function`` and don't unregister. They
        # leak into the global registry when the full test suite runs.
        if tool.name.startswith("stub_") or tool.name.startswith("test_"):
            continue
        unclassified.append(tool.name)

    assert not unclassified, (
        f"Tools missing from CORE / TOOLSETS / explicit fail-open "
        f"allowlist: {unclassified}.  Add them to the right group in "
        f"core/skills/toolsets.py (or to _INTENTIONAL_FAIL_OPEN in "
        f"this test if they're meant to stay un-classified)."
    )
