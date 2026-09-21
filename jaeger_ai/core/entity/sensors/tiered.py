"""Generic Tiered Perception Architecture (UPAA Principle 6 & ProAgent).

Contract:
- Tier 0: Cheap deterministic signals (timestamps, window names, idle state, telemetry, exit codes).
- Tier 1: Lightweight local classification / heuristics / fast embedding or pattern filter.
- Tier 2: Expensive multimodal model / LLM / vision / transcription only when justified by Tier 1.

Supports extensible modality inputs: desktop, microphone, camera, external robotics, mobile telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Callable, Sequence

from jaeger_ai.core.entity.events import JaegerEvent

logger = logging.getLogger("jaeger.entity.sensors.tiered")


class PerceptionTier(int, Enum):
    TIER_0_DETERMINISTIC = 0
    TIER_1_LOCAL_HEURISTIC = 1
    TIER_2_EXPENSIVE_MODEL = 2


@dataclass
class TieredObservation:
    source_sensor: str
    tier_reached: PerceptionTier
    signals: dict[str, Any]
    salience: float
    escalation_trail: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_event(self) -> JaegerEvent:
        return JaegerEvent.perception_sensed(
            sensor=self.source_sensor,
            signals={
                **self.signals,
                "perception_tier": self.tier_reached.value,
                "escalation_trail": self.escalation_trail,
            },
            salience=self.salience,
        )


import re


def redact_privacy_signals(signals: dict[str, Any]) -> dict[str, Any]:
    """Scrub sensitive credentials, auth tokens, passwords, and private identifiers."""
    redacted = dict(signals)
    # Redact common token patterns or password keys
    for k, v in list(redacted.items()):
        if any(s in k.lower() for s in ("token", "secret", "password", "key", "auth", "credential")):
            redacted[k] = "[REDACTED_CREDENTIAL]"
        elif isinstance(v, str):
            # Scrub bearer tokens / JWTs / hex keys
            v_scrubbed = re.sub(r"(?i)(bearer\s+[a-z0-9\-_\.]+)", "[REDACTED_AUTH]", v)
            v_scrubbed = re.sub(r"(?i)(api[_-]?key[:=]\s*[a-z0-9\-_]+)", "[REDACTED_API_KEY]", v_scrubbed)
            v_scrubbed = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED_EMAIL]", v_scrubbed)
            redacted[k] = v_scrubbed
    # If active_app or window title contains private indicators
    if "active_app" in redacted:
        app_name = str(redacted["active_app"]).lower()
        if any(p in app_name for p in ("1password", "bitwarden", "keepass", "keychain", "vault", "private")):
            redacted["active_app"] = "[PROTECTED_APP]"
    return redacted


class TieredPerceptionCoordinator:
    """Coordinates tiered signal intake, escalating only when justified."""

    def __init__(
        self,
        tier1_classifier: Callable[[dict[str, Any]], tuple[bool, float, str]] | None = None,
        tier2_model_evaluator: Callable[[dict[str, Any]], tuple[dict[str, Any], float, str]] | None = None,
        tier2_provider: Callable[[str, dict[str, Any]], str] | None = None,
    ) -> None:
        self.tier1_classifier = tier1_classifier or self._default_tier1_classifier
        self.tier2_provider = tier2_provider
        self.tier2_model_evaluator = tier2_model_evaluator or self._default_tier2_evaluator
        self.tier0_count = 0
        self.tier1_count = 0
        self.tier2_call_count = 0

    def _default_tier1_classifier(self, t0_signals: dict[str, Any]) -> tuple[bool, float, str]:
        """Cheap local heuristic: check if signals indicate an anomaly or critical alert."""
        alerts = t0_signals.get("alerts") or []
        active_app = str(t0_signals.get("active_app") or "")
        disk_free = float(t0_signals.get("disk_free_gb") or 999.0)

        if alerts or disk_free < 5.0 or "error" in active_app.lower() or "crash" in active_app.lower():
            # Escalate to Tier 2
            return True, 0.85, f"Anomaly detected in Tier 0: alerts={alerts}, disk_free={disk_free}GB"

        # Stays at Tier 0 / Routine
        return False, 0.2, "Routine activity within normal parameters"

    def _default_tier2_evaluator(self, t1_signals: dict[str, Any]) -> tuple[dict[str, Any], float, str]:
        """Synthesize rich context for escalated observation using model provider after privacy redaction."""
        self.tier2_call_count += 1
        redacted_context = redact_privacy_signals(t1_signals)
        rich_data = dict(redacted_context)

        if callable(self.tier2_provider):
            prompt = (
                f"Evaluate the following operational signals and assess anomaly urgency:\n"
                f"{redacted_context}"
            )
            synthesis = self.tier2_provider(prompt, redacted_context)
            rich_data["tier2_synthesis"] = synthesis
            rich_data["recommended_action"] = "Provider-evaluated operational action"
            return rich_data, 0.9, "Tier 2 model provider evaluation completed"

        rich_data["tier2_synthesis"] = "High priority operational anomaly assessed"
        rich_data["recommended_action"] = "Alert operator or initiate diagnostic"
        return rich_data, 0.9, "Tier 2 multimodal/reasoning assessment completed"

    def process(
        self,
        source_sensor: str,
        deterministic_signals: dict[str, Any],
        force_tier2: bool = False,
    ) -> TieredObservation:
        trail = ["Tier 0: Deterministic signal acquired"]
        signals = dict(deterministic_signals)
        salience = 0.2
        self.tier0_count += 1

        # 1. Tier 0 evaluation
        should_escalate_t1, t1_salience, t1_reason = self.tier1_classifier(signals)
        trail.append(f"Tier 1 Evaluation: {t1_reason}")

        if not should_escalate_t1 and not force_tier2:
            return TieredObservation(
                source_sensor=source_sensor,
                tier_reached=PerceptionTier.TIER_0_DETERMINISTIC,
                signals=signals,
                salience=salience,
                escalation_trail=trail,
            )

        # 2. Escalated to Tier 1
        self.tier1_count += 1
        salience = t1_salience
        signals["tier1_classified"] = True
        signals["tier1_reason"] = t1_reason

        # Check if Tier 1 warrants Tier 2 escalation
        if t1_salience >= 0.8 or force_tier2:
            trail.append("Escalating to Tier 2: Expensive model/multimodal evaluation")
            rich_signals, t2_salience, t2_reason = self.tier2_model_evaluator(signals)
            trail.append(f"Tier 2 Complete: {t2_reason}")
            return TieredObservation(
                source_sensor=source_sensor,
                tier_reached=PerceptionTier.TIER_2_EXPENSIVE_MODEL,
                signals=rich_signals,
                salience=t2_salience,
                escalation_trail=trail,
            )

        return TieredObservation(
            source_sensor=source_sensor,
            tier_reached=PerceptionTier.TIER_1_LOCAL_HEURISTIC,
            signals=signals,
            salience=salience,
            escalation_trail=trail,
        )
