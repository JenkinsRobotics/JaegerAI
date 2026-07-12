"""The enhanced /goal flow — skill-dev detection and goal-title helpers.

The interactive part (clarify questions, the disposition prompt) needs a
console and a model, so only the pure helpers are unit-tested here.
"""

from __future__ import annotations

from jaeger_ai.interfaces.tui.slash_commands import (
    _goal_title,
    _looks_like_skill_dev,
)
from jaeger_ai.main import clarify_goal


# ── skill-development detection → routes to Deep Think ───────────────


def test_skill_dev_goals_are_detected() -> None:
    for g in ("make a test skill. one that plays tic tac toe",
              "build a tool to fetch the weather",
              "create a new skill for reading PDFs",
              "implement a calculator capability"):
        assert _looks_like_skill_dev(g), g


def test_non_skill_dev_goals_are_not_flagged() -> None:
    for g in ("summarise my unread emails",
              "what is the capital of France",
              "plan a trip to Tokyo next month"):
        assert not _looks_like_skill_dev(g), g


# ── board-card title from a goal ─────────────────────────────────────


def test_goal_title_takes_first_nonblank_line() -> None:
    assert _goal_title("  make a skill\nwith more detail below") == "make a skill"


def test_goal_title_truncates_and_handles_empty() -> None:
    assert len(_goal_title("x" * 200)) <= 70
    assert _goal_title("   ") == "goal"


# ── clarify is robust without a model ────────────────────────────────


def test_clarify_goal_without_client_returns_no_questions() -> None:
    assert clarify_goal(None, "anything at all") == []
