"""The untrusted-content tool surface fails closed.

Ported alongside hermes-agent's ``_HERMES_WEBHOOK_SAFE_TOOLS``. The donor
gates by resolving a per-platform profile; Jaeger gates in ``tool_visible``,
so these tests pin the two properties that port depends on:

  * the gate holds with toolset scoping OFF (Jaeger's default, and the
    configuration a webhook turn actually runs in), and
  * the model cannot widen back out via ``load_tools``/``enable_toolset``.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from jaeger_agent.skill_registry import toolset_scoping as ts


@pytest.fixture(autouse=True)
def _clean_scoping():
    """Each test starts core-only and trusted, and leaves it that way."""
    ts.reset_toolsets()
    yield
    ts.reset_toolsets()


def test_untrusted_hides_dangerous_tools_with_scoping_off():
    """The default config is scoping-OFF; the gate must still bite there."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("JAEGER_TOOLSET_SCOPING", None)
        assert not ts._scoping_enabled()

        # Trusted: the full surface, including execution.
        assert ts.tool_visible("execute_code")
        assert ts.tool_visible("terminal")
        assert ts.tool_visible("write_file")

        with ts.untrusted_content():
            assert not ts.tool_visible("execute_code")
            assert not ts.tool_visible("terminal")
            assert not ts.tool_visible("write_file")
            assert not ts.tool_visible("read_file")
            assert not ts.tool_visible("memory")

        # Restored on exit.
        assert ts.tool_visible("execute_code")


def test_untrusted_allows_exactly_the_safe_four():
    with ts.untrusted_content():
        for name in ("web_search", "web_extract", "vision_analyze", "clarify"):
            assert ts.tool_visible(name), name
        assert {n for n in ts.UNTRUSTED_SAFE if ts.tool_visible(n)} == set(ts.UNTRUSTED_SAFE)


def test_untrusted_hides_the_meta_tools():
    """An untrusted turn cannot enumerate what it is missing."""
    with ts.untrusted_content():
        assert not ts.tool_visible("list_tools")
        assert not ts.tool_visible("describe_tool")
        assert not ts.tool_visible("load_tools")


def test_full_tools_escape_hatch_does_not_lift_the_gate():
    """JAEGER_FULL_TOOLS is a local debugging switch, not an injection path."""
    with mock.patch.dict(os.environ, {"JAEGER_FULL_TOOLS": "1"}):
        assert ts.tool_visible("terminal")
        with ts.untrusted_content():
            assert not ts.tool_visible("terminal")


def test_untrusted_cannot_widen_via_enable_toolset():
    with ts.untrusted_content():
        assert ts.enable_toolset("code") is False
        assert not ts.tool_visible("terminal")
    # And the refused call left no residue for the next trusted turn.
    assert "code" not in ts.active_toolset_names()


def test_untrusted_safe_is_not_a_nameable_toolset():
    """Membership in TOOLSETS would make it reachable from load_tools."""
    assert "untrusted_safe" not in ts.TOOLSETS
    assert "untrusted_safe" not in ts.all_toolsets()
    assert ts.enable_toolset("untrusted_safe") is False


def test_nesting_and_restore():
    assert not ts.is_untrusted_content()
    with ts.untrusted_content():
        assert ts.is_untrusted_content()
        with ts.untrusted_content():
            assert ts.is_untrusted_content()
        assert ts.is_untrusted_content()
    assert not ts.is_untrusted_content()


def test_safe_tools_are_real_registered_names():
    """A typo here would silently grant nothing — pin against the live map."""
    known = set(ts.CORE)
    for members in ts.TOOLSETS.values():
        known |= set(members)
    assert ts.UNTRUSTED_SAFE <= known, ts.UNTRUSTED_SAFE - known
