"""Hermes-compatible delegate_task argument shapes."""

from __future__ import annotations

from jaeger_ai.core.runtime.delegation import (
    LEAF,
    ORCHESTRATOR,
    collect_goals,
    leaf_child_depth,
    normalize_role,
)


def test_jaeger_subtasks_list_still_works():
    assert collect_goals(subtasks=["a", "b"]) == ["a", "b"]


def test_hermes_single_goal():
    assert collect_goals(goal="research the invoice") == ["research the invoice"]


def test_hermes_goal_plus_context():
    out = collect_goals(goal="summarise", context="the attached PDF")
    assert out == ["summarise\n\nContext:\nthe attached PDF"]


def test_hermes_tasks_list_of_strings():
    assert collect_goals(tasks=["one", "two"]) == ["one", "two"]


def test_hermes_tasks_list_of_dicts():
    out = collect_goals(tasks=[
        {"goal": "search A", "context": "docs"},
        {"task": "search B"},
    ])
    assert out[0].startswith("search A")
    assert "docs" in out[0]
    assert out[1] == "search B"


def test_empty_is_empty():
    assert collect_goals() == []
    assert collect_goals(subtasks=["", "  "]) == []


def test_role_defaults_to_leaf():
    assert normalize_role(None) == LEAF
    assert normalize_role("ORCHESTRATOR") == ORCHESTRATOR
    assert normalize_role("nope") == LEAF


def test_a_leaf_child_starts_at_the_cap():
    """So nested delegate_task hits the existing recursion guard."""
    assert leaf_child_depth(2) == 2
    assert leaf_child_depth(0) == 0
