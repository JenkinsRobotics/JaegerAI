"""Tool-surface audit — the consolidated 48-tool surface.

The 2026-05 tool audit merged four pairs/triples of overlapping tools:
  • launch_url + open_file + open_app  → open_on_host
  • speak + speak_file                → speak(text=, path=)
  • check_background + read_background → check_background(lines=)
  • delegate + delegate_parallel       → delegate(subtasks=[...])

These tests lock in that surface so a regression (re-adding a retired
name, or losing a merged one) fails loudly.
"""

from __future__ import annotations

from jaeger_os.agent import tools


RETIRED = ["launch_url", "open_file", "open_app", "speak_file", "read_background"]
MERGED_IN = ["open_on_host", "speak", "check_background"]


def test_retired_tool_names_are_gone():
    for name in RETIRED:
        assert not hasattr(tools, name), f"{name} should have been merged away"


def test_merged_tool_names_present():
    for name in MERGED_IN:
        assert hasattr(tools, name), f"{name} should exist after consolidation"


def test_open_on_host_rejects_empty_target():
    assert "error" in tools.open_on_host("")


def test_open_on_host_rejects_unknown_kind():
    result = tools.open_on_host("Safari", kind="bogus")
    assert "error" in result and "bogus" in result["error"]


def test_speak_rejects_empty_input():
    """speak with neither text nor path is a no-op error, not a crash."""
    result = tools.speak(text="", path="")
    assert result.get("spoken") is False
