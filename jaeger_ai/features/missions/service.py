"""Mission facade over Jaeger's durable nested commitments."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from jaeger_agent.cognition.commitments import Commitment, CommitmentStore


class MissionService:
    """Treat a mission as a root commitment with goal and plan-step children."""

    def __init__(self, commitments: CommitmentStore) -> None:
        self.commitments = commitments

    def create(
        self,
        title: str,
        goals: list[dict[str, Any] | str],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_title = str(title or "").strip()
        if not clean_title:
            raise ValueError("mission title is required")
        if not goals:
            raise ValueError("a mission requires at least one goal")
        normalized: list[tuple[str, dict[str, Any], list[str]]] = []
        for raw in goals:
            item = {"title": raw} if isinstance(raw, str) else dict(raw)
            goal_title = str(item.pop("title", "")).strip()
            if not goal_title:
                raise ValueError("goal title is required")
            raw_steps = item.pop("steps", [])
            if not isinstance(raw_steps, list):
                raise TypeError("goal steps must be a list")
            normalized.append(
                (goal_title, item, [str(step).strip() for step in raw_steps if str(step).strip()])
            )
        mission = self.commitments.create(
            clean_title,
            kind="mission",
            payload=dict(metadata or {}),
        )
        created_goals: list[Commitment] = []
        for goal_title, item, steps in normalized:
            goal = self.commitments.create(
                goal_title,
                kind="goal",
                payload=item,
                parent_id=mission.id,
            )
            created_goals.append(goal)
            for step_title in steps:
                self.commitments.create(
                    step_title,
                    kind="plan_step",
                    parent_id=goal.id,
                )
        return self.describe(mission.id)

    def describe(self, mission_id: str) -> dict[str, Any]:
        mission = self.commitments.get(mission_id)
        if mission is None or mission.kind != "mission":
            raise KeyError(f"mission not found: {mission_id}")
        goals = []
        for goal in self.commitments.children(mission.id):
            row = asdict(goal)
            row["steps"] = [
                asdict(step) for step in self.commitments.children(goal.id)
            ]
            goals.append(row)
        return {"mission": asdict(mission), "goals": goals}

    def list(self, *, state: str | None = None) -> list[dict[str, Any]]:
        return [
            self.describe(item.id)
            for item in self.commitments.list(state=state)
            if item.kind == "mission"
        ]

    def transition(self, commitment_id: str, state: str) -> dict[str, Any]:
        return asdict(self.commitments.transition(commitment_id, state))
