"""Epistemic learning loop for ARES.

Records cause-and-effect relationships from executed intents, updates belief
heuristics, and prevents repeating ineffective actions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .belief import EpistemicContext
from .intent import CognitiveIntent
from .transducers.base import TransductionResult

logger = logging.getLogger(__name__)


@dataclass
class CauseAndEffectRecord:
    intent_id: str
    intent_kind: str
    goal: str
    target_medium: str
    success: bool
    outcome_summary: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_kind": self.intent_kind,
            "goal": self.goal,
            "target_medium": self.target_medium,
            "success": self.success,
            "outcome_summary": self.outcome_summary,
            "timestamp": self.timestamp,
        }


class EpistemicLearningLoop:
    """Tracks outcomes, learns cause-and-effect, and updates long-term belief models."""

    def __init__(self, context: EpistemicContext, log_dir: Path | str | None = None) -> None:
        self.context = context
        default_base = os.environ.get("JAEGER_HOME") or os.path.expanduser("~/.jaeger")
        self.log_dir = Path(log_dir or Path(default_base) / "ares").resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "cause_and_effect.jsonl"

    async def record_outcome(self, intent: CognitiveIntent, results: list[TransductionResult]) -> None:
        if not results:
            return

        all_success = all(r.success for r in results)
        summary = "; ".join(f"{r.medium.value}: {r.output[:100]}" for r in results)

        record = CauseAndEffectRecord(
            intent_id=intent.id,
            intent_kind=intent.kind.value,
            goal=intent.goal,
            target_medium=intent.target_medium.value,
            success=all_success,
            outcome_summary=summary,
        )

        # 1. Append to durable cause-and-effect log
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as exc:
            logger.warning("Failed to write ARES cause-and-effect log: %s", exc)

        # 2. Update epistemic context insight
        if all_success:
            self.context.add_insight(f"Successfully acted on: {intent.goal}")
        else:
            self.context.add_insight(f"Action encountered resistance on: {intent.goal}")
