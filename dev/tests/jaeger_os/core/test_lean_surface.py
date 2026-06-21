"""Lean tool surface + the consolidated memory tool.

There used to be TWO visibility models in this module:

  * ``model_visible()`` — "hermes-sized lean surface by default,
    JAEGER_FULL_TOOLS as kill-switch". An aspirational design that
    nothing in the agent loop ever actually called.
  * ``tool_visible()`` — the gate the agent *actually* uses. Opt-in
    via ``JAEGER_TOOLSET_SCOPING``; defaults to "every registered
    tool visible" (fail-open) and tightens to "CORE plus loaded
    toolsets" when scoping is on.

The duplicate was a footgun, so ``model_visible`` was removed. This
file pins ``tool_visible`` — the live gate — at both default and
scoped settings.

It also pins LEAN_CORE's *size* as a name set (used by the doctor's
tool-registry check) and the consolidated memory tool's
action-dispatch contract.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_os.agent import tools
from jaeger_os.agent.skill_registry.toolset_scoping import (
    CORE, LEAN_CORE, enable_toolset, reset_toolsets, tool_visible,
)


# ── tool_visible — the live gate ──────────────────────────────────


def test_default_is_fail_open(monkeypatch) -> None:
    """With ``JAEGER_TOOLSET_SCOPING`` unset (the shipped default),
    every tool is visible. A model that gets too many tools is a
    routing concern, not a hard refusal."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    reset_toolsets()
    assert tool_visible("get_time") is True
    assert tool_visible("execute_code") is True
    assert tool_visible("anything_unregistered") is True


def test_scoping_on_shows_core_hides_unloaded_toolsets(monkeypatch) -> None:
    """With scoping ON, only CORE tools and tools from *loaded*
    toolsets are visible. Unclassified tools still fail-open (the
    safer default — a new tool isn't silently hidden).

    Probe is ``terminal`` — in the ``code`` toolset since
    ``execute_code`` was promoted into CORE."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    reset_toolsets()
    # CORE always visible.
    assert tool_visible("get_time") is True
    # ``terminal`` lives in the ``code`` toolset — hidden until
    # someone calls load_toolset("code").
    assert tool_visible("terminal") is False
    # Unclassified tool fails open.
    assert tool_visible("a_brand_new_uncategorised_tool") is True


def test_load_toolset_reveals_its_members(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    reset_toolsets()
    assert tool_visible("terminal") is False
    enable_toolset("code")
    assert tool_visible("terminal") is True


# ── LEAN_CORE / CORE — name sets the doctor pins against ────────


def test_lean_core_is_hermes_sized() -> None:
    """LEAN_CORE is a curated name set (used by ``--doctor`` for
    tool-registry coverage). Pin its size so a runaway addition
    doesn't quietly bloat the bench's idea of "core"."""
    assert 12 <= len(LEAN_CORE) <= 26


def test_core_and_lean_core_share_an_intentional_subset() -> None:
    """LEAN_CORE is the hermes-style action-dispatch tier; CORE is
    the JROS always-visible set. They overlap on the obvious
    primitives — ``read_file``, ``write_file``, ``memory`` — so the
    doctor can cross-check both name sets resolve."""
    assert CORE & LEAN_CORE  # non-empty intersection


# ── consolidated memory tool ─────────────────────────────────────────


@pytest.fixture()
def bound(tmp_path):
    from jaeger_os.core.memory import memory as mem
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


def test_memory_remember_then_recall(bound) -> None:
    r = tools.memory(action="remember", key="hometown", value="Seattle",
                     category="contacts")
    assert r["ok"] is True
    got = tools.memory(action="recall", key="hometown")
    assert got["ok"] is True and got["value"] == "Seattle"


def test_memory_forget(bound) -> None:
    tools.memory(action="remember", key="x", value="1")
    assert tools.memory(action="forget", key="x")["ok"] is True
    assert tools.memory(action="recall", key="x")["found"] is False


def test_memory_list_groups_by_category(bound) -> None:
    tools.memory(action="remember", key="sara", value="555",
                 category="contacts")
    r = tools.memory(action="list")
    assert r["ok"] is True
    assert "contacts" in r["by_category"]


def test_memory_search_action_runs(bound) -> None:
    r = tools.memory(action="search", query="anything")
    assert r["ok"] is True  # found may be 0; the action must not error


def test_memory_rejects_unknown_action(bound) -> None:
    r = tools.memory(action="teleport")
    assert r["ok"] is False and "unknown" in r["error"]


def test_memory_remember_needs_key_and_value(bound) -> None:
    assert tools.memory(action="remember", key="only_key")["ok"] is False
