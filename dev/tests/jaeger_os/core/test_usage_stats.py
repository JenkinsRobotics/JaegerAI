"""Tool + skill usage telemetry (audit gap #4).

A JSON sidecar counts tool calls (with failures + elapsed) and skill
views, so the agent can answer "which tools fail" / "which skills are
dead weight." Best-effort: a telemetry write never breaks a turn.
"""

from __future__ import annotations

import pytest

from jaeger_os.agent import tools
from jaeger_os.core.runtime import usage_stats
from jaeger_os.core.instance.instance import InstanceLayout


@pytest.fixture()
def bound(tmp_path):
    """A temp instance with tools bound + a fresh usage accumulator."""
    layout = InstanceLayout(root=tmp_path / "inst")
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    tools.bind(layout)
    usage_stats._stats = None   # force a reload from this instance
    return layout


def test_record_tool_counts_calls_and_failures(bound) -> None:
    usage_stats.record_tool("web_search", ok=True, elapsed=1.5)
    usage_stats.record_tool("web_search", ok=False, elapsed=0.5)
    row = usage_stats.snapshot()["tools"]["web_search"]
    assert row["calls"] == 2
    assert row["failures"] == 1
    assert row["total_s"] == 2.0
    assert row["last_used"]


def test_record_skill_counts_views(bound) -> None:
    usage_stats.record_skill("codebase-inspection")
    usage_stats.record_skill("codebase-inspection")
    assert usage_stats.snapshot()["skills"]["codebase-inspection"]["views"] == 2


def test_top_tools_is_sorted_by_calls(bound) -> None:
    for _ in range(3):
        usage_stats.record_tool("read_file")
    usage_stats.record_tool("write_file")
    top = usage_stats.top_tools()
    assert top[0]["name"] == "read_file" and top[0]["calls"] == 3


def test_counters_persist_to_disk(bound) -> None:
    usage_stats.record_tool("terminal", elapsed=2.0)
    usage_stats._stats = None   # drop in-memory → must reload from disk
    assert usage_stats.snapshot()["tools"]["terminal"]["calls"] == 1


def test_reset_clears_counters(bound) -> None:
    usage_stats.record_tool("x")
    usage_stats.reset()
    assert usage_stats.snapshot() == {"tools": {}, "skills": {}}


def test_empty_name_is_ignored(bound) -> None:
    usage_stats.record_tool("")
    usage_stats.record_skill("")
    assert usage_stats.snapshot() == {"tools": {}, "skills": {}}
