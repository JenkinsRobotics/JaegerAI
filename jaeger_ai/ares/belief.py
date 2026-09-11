"""Unbroken epistemic context fabric for ARES.

Maintains an enduring rolling belief state across sessions and turns,
interfacing with Honcho shared memory and preventing latest-turn amnesia.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jaeger_ai.features.shared_memory.honcho_client import HonchoClient

logger = logging.getLogger(__name__)


@dataclass
class GoalRecord:
    id: str
    description: str
    created_at: float = field(default_factory=time.time)
    completed: bool = False
    priority: int = 1


@dataclass
class OperatorProfile:
    name: str = "Matthew Jenkins"
    communication_style: str = "concise, direct, high-agency"
    frequent_projects: list[str] = field(default_factory=lambda: ["ARES", "JaegerAI", "Finances"])
    learned_preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class BeliefState:
    updated_at: float = field(default_factory=time.time)
    operator: OperatorProfile = field(default_factory=OperatorProfile)
    active_goals: list[GoalRecord] = field(default_factory=list)
    recent_insights: list[str] = field(default_factory=list)
    system_confidence: float = 0.95
    unbroken_narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "updated_at": self.updated_at,
            "operator": {
                "name": self.operator.name,
                "communication_style": self.operator.communication_style,
                "frequent_projects": self.operator.frequent_projects,
                "learned_preferences": self.operator.learned_preferences,
            },
            "active_goals": [
                {"id": g.id, "desc": g.description, "completed": g.completed}
                for g in self.active_goals
            ],
            "recent_insights": self.recent_insights[-5:],
            "system_confidence": self.system_confidence,
            "unbroken_narrative": self.unbroken_narrative,
        }


class EpistemicContext:
    """Maintains and updates the agent's enduring worldview without amnesia."""

    def __init__(self, cache_dir: Path | str | None = None) -> None:
        default_base = os.environ.get("JAEGER_HOME") or os.path.expanduser("~/.jaeger")
        self.cache_dir = Path(cache_dir or Path(default_base) / "ares").resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self.cache_dir / "belief_state.json"
        self._honcho = HonchoClient()
        self._state = self._load_local_state()

    @property
    def current(self) -> BeliefState:
        return self._state

    def _load_local_state(self) -> BeliefState:
        if not self._state_file.exists():
            return BeliefState()
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            operator_data = data.get("operator", {})
            operator = OperatorProfile(
                name=operator_data.get("name", "Matthew Jenkins"),
                communication_style=operator_data.get("communication_style", "concise, direct"),
                frequent_projects=operator_data.get("frequent_projects", ["ARES", "JaegerAI"]),
                learned_preferences=operator_data.get("learned_preferences", {}),
            )
            goals = [
                GoalRecord(id=g["id"], description=g["desc"], completed=g.get("completed", False))
                for g in data.get("active_goals", [])
            ]
            return BeliefState(
                updated_at=data.get("updated_at", time.time()),
                operator=operator,
                active_goals=goals,
                recent_insights=data.get("recent_insights", []),
                system_confidence=data.get("system_confidence", 0.95),
                unbroken_narrative=data.get("unbroken_narrative", ""),
            )
        except Exception as exc:
            logger.warning("Failed to parse ARES belief state, resetting to clean state: %s", exc)
            return BeliefState()

    def persist(self) -> None:
        try:
            self._state.updated_at = time.time()
            self._state_file.write_text(
                json.dumps(self._state.to_dict(), indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist ARES belief state: %s", exc)

    async def orient(self, snapshot: Any) -> BeliefState:
        """Update the belief state by integrating the latest perception into the permanent context."""
        # Check Honcho memory for external updates
        try:
            honcho_status = self._honcho.status()
            if honcho_status.get("status") == "healthy":
                # Successfully reached Honcho server, sync preferences
                pass
        except Exception:
            pass

        # Update narrative based on repo drift & alerts
        narrative_parts = [
            f"Active on {snapshot.repo.branch or 'workspace'} with {snapshot.repo.dirty_files_count} modified files."
        ]
        if snapshot.active_alerts:
            narrative_parts.append(f"Attention needed: {'; '.join(snapshot.active_alerts)}.")

        self._state.unbroken_narrative = " ".join(narrative_parts)
        self.persist()
        return self._state

    def add_insight(self, insight: str) -> None:
        """Records an enduring realization or observation into permanent context."""
        if insight not in self._state.recent_insights:
            self._state.recent_insights.append(insight)
            if len(self._state.recent_insights) > 20:
                self._state.recent_insights.pop(0)
            self.persist()

    def record_goal(self, goal_id: str, description: str) -> None:
        if not any(g.id == goal_id for g in self._state.active_goals):
            self._state.active_goals.append(GoalRecord(id=goal_id, description=description))
            self.persist()

    def mark_goal_completed(self, goal_id: str) -> None:
        for g in self._state.active_goals:
            if g.id == goal_id:
                g.completed = True
        self.persist()
