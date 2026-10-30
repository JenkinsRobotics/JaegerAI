"""GoalService — durable operator goals with tool-bundle caps."""

import pytest
from jaeger_agent.cognition.commitments import (
    CommitmentError,
    InMemoryCommitmentStore,
)

from jaeger_ai.features.goals import GoalService


def test_goal_create_with_project_and_bundle() -> None:
    service = GoalService(InMemoryCommitmentStore())
    result = service.create(
        "Ship robot arm v2",
        objective="Arm moves to commanded pose",
        project="Robot Arm",
        tool_bundle="robotics.build",
        success_criteria="swift test passes",
    )
    assert result["goal"]["kind"] == "goal"
    assert result["goal"]["payload"]["tool_bundle"] == "robotics.build"
    assert result["goal"]["payload"]["objective"] == "Arm moves to commanded pose"
    assert result["project"]["kind"] == "project"
    assert result["project"]["title"] == "Robot Arm"
    assert result["goal"]["parent_id"] == result["project"]["id"]


def test_goal_create_rejects_unknown_bundle() -> None:
    service = GoalService(InMemoryCommitmentStore())
    with pytest.raises(ValueError, match="unknown tool_bundle"):
        service.create("X", tool_bundle="robotics.deply")  # typo must fail


def test_goal_list_and_describe() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.create("Goal A", project="P")
    listed = service.list()
    assert len(listed) == 1
    assert listed[0]["goal"]["id"] == created["goal"]["id"]
    described = service.describe(created["goal"]["id"])
    assert described["goal"]["title"] == "Goal A"


def test_goal_update_edits_payload_and_clears_bundle() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.create("G", tool_bundle="goals")
    goal_id = created["goal"]["id"]
    updated = service.update(goal_id, objective="new objective", tool_bundle="")
    assert updated["goal"]["payload"].get("objective") == "new objective"
    assert "tool_bundle" not in updated["goal"]["payload"]


def test_goal_update_rejects_unknown_bundle() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.create("G")
    with pytest.raises(ValueError, match="unknown tool_bundle"):
        service.update(created["goal"]["id"], tool_bundle="nope")


def test_project_status_rolls_up_goals() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.create("Goal A", project="Robot Arm")
    project_id = created["project"]["id"]
    status = service.project_status(project_id)
    assert status["project"]["title"] == "Robot Arm"
    assert len(status["goals"]) == 1
    assert status["goals"][0]["goal"]["title"] == "Goal A"


def test_transition_open_children_guard_still_holds() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.create("Goal A", project="P")
    project_id = created["project"]["id"]
    service.transition(created["goal"]["id"], "active")
    # The project parent cannot complete while the goal child is open.
    with pytest.raises(CommitmentError, match="cannot"):
        service.transition(project_id, "completed")
