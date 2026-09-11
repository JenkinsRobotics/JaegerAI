"""Visual medium transducer for macOS UI cards, notifications, and orb states.

Desktop notifications only fire when ``allow_notifications`` is True (default False).
Event cards are always appended under ``~/.jaeger/ares/`` for the Work stage.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from ..intent import CognitiveIntent, MediumType
from .base import TransductionResult

logger = logging.getLogger(__name__)


class VisualTransducer:
    """Transforms intent into visual cards, optional desktop notifications, and orb states."""

    def __init__(
        self,
        events_dir: Path | str | None = None,
        *,
        allow_notifications: bool = False,
    ) -> None:
        default_base = (
            os.environ.get("JAEGER_STATE_DIR")
            or os.environ.get("JAEGER_HOME")
            or os.path.expanduser("~/.jaeger")
        )
        self.events_dir = Path(events_dir or Path(default_base) / "ares").resolve()
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.events_file = self.events_dir / "events.jsonl"
        self.allow_notifications = bool(allow_notifications)

    async def transduce(self, intent: CognitiveIntent) -> TransductionResult:
        card = {
            "id": intent.id,
            "kind": intent.kind.value,
            "goal": intent.goal,
            "reasoning": intent.reasoning,
            "salience": intent.salience,
            "valence": intent.emotional_valence,
            "timestamp": intent.created_at,
        }

        try:
            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(card) + "\n")
        except OSError as exc:
            logger.warning("Failed to append ARES visual event card: %s", type(exc).__name__)

        notified = False
        if self.allow_notifications and intent.salience >= 0.85:
            notified = self._post_macos_notification(
                title="ARES Cognitive Alert",
                message=intent.goal,
            )

        return TransductionResult(
            success=True,
            medium=MediumType.VISUAL,
            output=f"Emitted visual event card: {intent.goal}",
            metadata={
                "card": card,
                "macos_notification": notified,
                "allow_notifications": self.allow_notifications,
            },
        )

    def _post_macos_notification(self, title: str, message: str) -> bool:
        try:
            clean_title = title.replace('"', '\\"')
            clean_msg = message.replace('"', '\\"')
            script = f'display notification "{clean_msg}" with title "{clean_title}" sound name "Glass"'
            subprocess.run(["osascript", "-e", script], timeout=2, capture_output=True)
            return True
        except Exception:
            return False
