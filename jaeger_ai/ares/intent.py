"""Endogenous reasoner and intent formation for ARES.

Generates internal goals and intents based on perceived world state,
unbroken belief context, and homeostatic drives (stability, accuracy, assistance).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .belief import BeliefState
from .perception import PerceptionSnapshot


class IntentKind(str, Enum):
    SILENT_VIGIL = "silent_vigil"
    SYSTEM_MAINTENANCE = "system_maintenance"
    INSIGHT_BROADCAST = "insight_broadcast"
    OPERATOR_ASSIST = "operator_assist"


class MediumType(str, Enum):
    SYSTEM = "system"        # Code execution, test run, git commit
    VISUAL = "visual"        # UI card push, desktop notification, orb pulse
    ACOUSTIC = "acoustic"    # Tone, sound envelope, TTS voice inflection
    MULTI_MODAL = "multi_modal"


@dataclass
class CognitiveIntent:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    kind: IntentKind = IntentKind.SILENT_VIGIL
    goal: str = ""
    reasoning: str = ""
    salience: float = 0.0           # 0.0 (negligible) to 1.0 (vital)
    emotional_valence: str = "calm" # "calm", "urgent", "reassuring", "analytical"
    target_medium: MediumType = MediumType.SYSTEM
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def is_active(self) -> bool:
        """True only if salience exceeds activation threshold (0.5)."""
        return self.salience >= 0.5 and self.kind != IntentKind.SILENT_VIGIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "goal": self.goal,
            "reasoning": self.reasoning,
            "salience": round(self.salience, 2),
            "emotional_valence": self.emotional_valence,
            "target_medium": self.target_medium.value,
            "payload": self.payload,
            "created_at": self.created_at,
            "is_active": self.is_active,
        }


class IntentEngine:
    """Evaluates world state against belief context to form endogenous intents."""

    def __init__(self, salience_threshold: float = 0.5) -> None:
        self.salience_threshold = salience_threshold

    async def form_intent(self, snapshot: PerceptionSnapshot, belief: BeliefState) -> CognitiveIntent:
        """Evaluates world state and belief context, returning an actionable or vigil intent."""

        # 1. Critical System Alerts (Low Disk Space)
        if snapshot.system.disk_free_gb < 5.0 and snapshot.system.disk_total_gb > 0:
            return CognitiveIntent(
                kind=IntentKind.INSIGHT_BROADCAST,
                goal="Alert operator to imminent disk space exhaustion",
                reasoning=f"Disk free space is critically low at {snapshot.system.disk_free_gb} GB.",
                salience=0.95,
                emotional_valence="urgent",
                target_medium=MediumType.VISUAL,
                payload={"action": "clean_scratch_caches", "disk_free": snapshot.system.disk_free_gb},
            )

        # 2. Financial Anomalies or Pacing Drift
        if snapshot.finance.anomalies_detected:
            return CognitiveIntent(
                kind=IntentKind.INSIGHT_BROADCAST,
                goal="Flag unreviewed financial anomalies or budget pacing",
                reasoning="Monarch Money service detected unreviewed charges or pacing alerts.",
                salience=0.80,
                emotional_valence="analytical",
                target_medium=MediumType.VISUAL,
                payload={"unreviewed_count": snapshot.finance.unreviewed_count},
            )

        # 3. High Working-Tree Drift (Dirty Git files accumulating)
        if snapshot.repo.dirty_files_count >= 20:
            return CognitiveIntent(
                kind=IntentKind.OPERATOR_ASSIST,
                goal="Propose repository hygiene review or branch checkpoint",
                reasoning=f"Working tree has accumulated {snapshot.repo.dirty_files_count} uncommitted changes.",
                salience=0.65,
                emotional_valence="reassuring",
                target_medium=MediumType.MULTI_MODAL,
                payload={"dirty_files": snapshot.repo.dirty_files_count},
            )

        # 4. Open Incomplete Goals
        pending_goals = [g for g in belief.active_goals if not g.completed]
        if pending_goals and snapshot.operator.idle_seconds > 300:
            top_goal = pending_goals[0]
            return CognitiveIntent(
                kind=IntentKind.SYSTEM_MAINTENANCE,
                goal=f"Advance autonomous work on goal: {top_goal.description}",
                reasoning="Operator is idle and pending high-priority goals remain in belief state.",
                salience=0.70,
                emotional_valence="focused",
                target_medium=MediumType.SYSTEM,
                payload={"goal_id": top_goal.id, "desc": top_goal.description},
            )

        # 5. Homeostasis / Vigilance (Everything healthy)
        return CognitiveIntent(
            kind=IntentKind.SILENT_VIGIL,
            goal="Maintain ambient observation",
            reasoning="System, repository, and operator state in equilibrium.",
            salience=0.1,
            emotional_valence="calm",
            target_medium=MediumType.SYSTEM,
        )
