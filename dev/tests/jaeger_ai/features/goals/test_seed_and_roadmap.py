"""Seeding + built-in roadmap — every phase captured as a durable goal."""

from jaeger_agent.cognition.commitments import InMemoryCommitmentStore

from jaeger_ai.features.goals import GoalService, roadmap_projects
from jaeger_ai.features.goals.roadmap import ROADMAP_PROJECT


def test_roadmap_has_all_production_phases() -> None:
    """The built-in roadmap must capture every phase of the production plan."""
    phases = ROADMAP_PROJECT["phases"]
    titles = [p["title"] for p in phases]
    # All 10 phases present, in order.
    assert len(phases) == 10
    assert titles[0].startswith("Phase 1")
    assert titles[-1].startswith("Phase 10")
    # Each phase has the fields seeding needs.
    for phase in phases:
        assert phase.get("title")
        assert phase.get("objective")
        assert phase.get("tool_bundle")
        assert phase.get("success_criteria")


def test_roadmap_phases_use_known_bundles() -> None:
    from jaeger_ai.contract.tool_bundles import is_known_bundle
    for phase in ROADMAP_PROJECT["phases"]:
        assert is_known_bundle(phase["tool_bundle"]), (
            f"phase {phase['title']!r} uses unknown bundle {phase['tool_bundle']!r}"
        )


def test_seed_roadmap_creates_project_with_goal_per_phase() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.seed_from_config(roadmap_projects())
    # One goal per phase → 10 goals.
    assert len(created) == 10
    # All under one project.
    project_ids = {c["project"]["id"] for c in created}
    assert len(project_ids) == 1
    project = created[0]["project"]
    assert project["title"] == "JaegerAI Production"
    assert project["payload"]["source_name"] == "JaegerAI Production"
    # Goals carry their phase tool_bundle.
    bundles = {c["goal"]["payload"].get("tool_bundle") for c in created}
    assert "robotics.build" in bundles
    assert "content" in bundles
    assert "goals" in bundles


def test_seed_is_idempotent() -> None:
    service = GoalService(InMemoryCommitmentStore())
    first = service.seed_from_config(roadmap_projects())
    second = service.seed_from_config(roadmap_projects())
    assert len(first) == 10
    assert second == []  # nothing new on re-seed
    # Still exactly 10 goals + 1 project in the store.
    goals = [g for g in service.list()]
    assert len(goals) == 10


def test_seed_operator_projects_alongside_roadmap() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.seed_from_config(
        roadmap_projects()
        + (
            {"name": "Robot Arm v2", "tool_bundle": "robotics.build",
             "root": "/projects/arm",
             "phases": [
                 {"title": "Build arm firmware", "tool_bundle": "robotics.build"},
                 {"title": "Deploy to arm", "tool_bundle": "robotics.deploy"},
             ]},
        )
    )
    # 10 roadmap + 2 operator phases.
    assert len(created) == 12
    operator = [c for c in created if c["project"]["title"] == "Robot Arm v2"]
    assert len(operator) == 2
    bundles = {c["goal"]["payload"].get("tool_bundle") for c in operator}
    assert bundles == {"robotics.build", "robotics.deploy"}


def test_seed_operator_project_without_phases_creates_kickoff_goal() -> None:
    service = GoalService(InMemoryCommitmentStore())
    created = service.seed_from_config((
        {"name": "Episode 12", "tool_bundle": "content",
         "objective": "Publish episode 12"},
    ))
    assert len(created) == 1
    assert created[0]["goal"]["title"] == "Kick off Episode 12"
    assert created[0]["goal"]["payload"]["objective"] == "Publish episode 12"
    assert created[0]["goal"]["payload"]["tool_bundle"] == "content"


def test_seeded_goals_are_listable_and_describable() -> None:
    """Seeded goals must be visible to the goal_* tools (list/describe)."""
    service = GoalService(InMemoryCommitmentStore())
    service.seed_from_config(roadmap_projects())
    listed = service.list()
    assert len(listed) == 10
    # Every listed goal is describable (no dangling ids).
    for row in listed:
        desc = service.describe(row["goal"]["id"])
        assert desc["goal"]["title"]
