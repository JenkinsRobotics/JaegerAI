import pytest
from jaeger_agent.cognition.commitments import (
    CommitmentError,
    InMemoryCommitmentStore,
)

from jaeger_ai.features.missions import MissionService


def test_mission_creates_goal_and_plan_step_tree() -> None:
    service = MissionService(InMemoryCommitmentStore())
    result = service.create(
        "Ship orchestrator",
        [{"title": "Delegate work", "runtime": "codex", "steps": ["probe", "run"]}],
    )
    assert result["mission"]["kind"] == "mission"
    assert result["goals"][0]["payload"] == {"runtime": "codex"}
    assert [step["title"] for step in result["goals"][0]["steps"]] == ["probe", "run"]


def test_open_children_prevent_false_mission_completion() -> None:
    service = MissionService(InMemoryCommitmentStore())
    result = service.create("Mission", ["Goal"])
    mission_id = result["mission"]["id"]
    service.transition(mission_id, "active")
    with pytest.raises(CommitmentError, match="open children"):
        service.transition(mission_id, "completed")
