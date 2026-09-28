"""Deterministic salience and restraint for Tier 3 proactive turns."""
from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from enum import IntEnum
from typing import Any, Protocol

from jaeger_ai.contract.ports import OLLAMA_URL


class SalienceLevel(IntEnum):
    """Delivery contract: quiet, remembered, staged, or waking."""

    NOISE = 0
    JOURNAL = 1
    DIGEST = 2
    IMMEDIATE = 3


class SalienceEvent(Protocol):
    """Structural subset of :class:`SensorEvent` used by the classifier."""

    source: str
    kind: str
    summary: str
    details: dict[str, Any]


ModelClassifier = Callable[[SalienceEvent], SalienceLevel]
_AUTOSAVE_HINTS = ("autosave", "auto-save", ".swp", "~", ".tmp", ".partial")


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


class SalienceClassifier:
    """Fast deterministic rules; ambiguous events may ask the awake model."""

    def __init__(
        self,
        *,
        awake_model: str = "gemma4",
        model_evaluator: ModelClassifier | None = None,
        model_timeout_s: float = 2.0,
    ) -> None:
        self.awake_model = awake_model
        self.model_evaluator = model_evaluator or self._ask_ollama
        self.model_timeout_s = model_timeout_s

    def classify(self, event: SalienceEvent) -> SalienceLevel:
        """Classify one event. Fast rules win; failures never become alarms."""
        level = self.rules(event)
        if level is not None:
            return level
        try:
            result = self.model_evaluator(event)
        except Exception:  # noqa: BLE001
            return SalienceLevel.JOURNAL
        return result if isinstance(result, SalienceLevel) else SalienceLevel.JOURNAL

    def rules(self, event: SalienceEvent) -> SalienceLevel | None:
        kind = str(event.kind).lower()
        text = " ".join([
            str(event.summary).lower(),
            _compact_json(event.details).lower(),
        ])

        if kind in {"test_failed", "test_failure"} or ("test" in kind and "failed" in text):
            return SalienceLevel.IMMEDIATE
        if kind in {"disk_low", "memory_pressure", "memory_pressure_critical"}:
            return SalienceLevel.IMMEDIATE
        if kind == "long_task_completed":
            return SalienceLevel.IMMEDIATE
        if kind == "branch_changed":
            return SalienceLevel.DIGEST
        if kind in {"file_changed", "file_added", "file_removed"}:
            path = str(event.details.get("path") or event.summary)
            if any(hint in path.lower() for hint in _AUTOSAVE_HINTS):
                return SalienceLevel.NOISE
            return SalienceLevel.JOURNAL
        if kind == "battery_low":
            return SalienceLevel.JOURNAL
        if "failed" in text or "critical" in text:
            return SalienceLevel.IMMEDIATE
        return None

    def _ask_ollama(self, event: SalienceEvent) -> SalienceLevel:
        """Use the configured local awake model only as the ambiguity fallback."""
        payload = {
            "model": self.awake_model,
            "messages": [{
                "role": "user",
                "content": (
                    "Classify this sensor observation as exactly one of NOISE, "
                    "JOURNAL, DIGEST, or IMMEDIATE. Only urgent test/system "
                    "failures are IMMEDIATE. Reply with the single word.\n"
                    f"Summary: {event.summary}\nDetails: {_compact_json(event.details)}"
                ),
            }],
            "stream": False,
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.model_timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = str((body.get("message") or {}).get("content") or body.get("response") or "")
        try:
            return SalienceLevel[str(text.strip().upper())]
        except KeyError:
            return SalienceLevel.JOURNAL


__all__ = ["SalienceClassifier", "SalienceLevel"]
