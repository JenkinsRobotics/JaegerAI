"""Lightweight Attention and Salience Engine (Pinocchio Architecture).

Separates passive state tracking from cognitive wakeups.
Ensures that routine telemetry, passive observations, and quiet heartbeats
update state and event logs with ZERO expensive LLM calls.
Only events that exceed the salience threshold wake cognition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .events import EventType, JaegerEvent
from .self_state import SelfState


class SalienceLevel(float, Enum):
    PASSIVE = 0.1
    ROUTINE = 0.3
    ATTENTION = 0.6
    URGENT = 0.9

    # Compatibility Aliases
    IGNORED = 0.1
    LOW = 0.3
    MEDIUM = 0.6
    HIGH = 0.6
    CRITICAL = 0.9


@dataclass(frozen=True)
class AttentionDecision:
    wake_cognition: bool
    salience: float
    reason: str
    target_role: str = "lead"

    @property
    def level(self) -> SalienceLevel:
        if self.salience >= 0.85:
            return SalienceLevel.URGENT
        if self.salience >= 0.55:
            return SalienceLevel.ATTENTION
        if self.salience >= 0.25:
            return SalienceLevel.ROUTINE
        return SalienceLevel.PASSIVE


class SalienceEngine:
    """Evaluates whether an incoming event warrants invoking cognition."""

    def __init__(self, wake_threshold: float = 0.7) -> None:
        self.wake_threshold = wake_threshold

    def evaluate(self, event: JaegerEvent, state: SelfState) -> AttentionDecision:
        etype = event.event_type
        payload = event.payload or {}

        # 1. Direct human interaction always wakes cognition
        if etype == EventType.HUMAN_MESSAGE.value:
            return AttentionDecision(
                wake_cognition=True,
                salience=1.0,
                reason="human direct prompt",
            )

        # 2. Standing Heartbeat: silent unless work/briefing is required
        if etype == EventType.SYSTEM_HEARTBEAT.value:
            requires_briefing = bool(payload.get("pending_briefing"))
            has_urgent_work = bool(payload.get("urgent_work"))
            if requires_briefing or has_urgent_work:
                return AttentionDecision(
                    wake_cognition=True,
                    salience=0.8,
                    reason=f"heartbeat active need: {'briefing' if requires_briefing else 'work'}",
                )
            return AttentionDecision(
                wake_cognition=False,
                salience=SalienceLevel.PASSIVE.value,
                reason="heartbeat quiet: standing checklist ok",
            )

        # 3. Perception / Sensor Telemetry
        if etype in (EventType.PERCEPTION_SENSED.value, EventType.SYSTEM_OBSERVATION.value):
            alerts = payload.get("alerts") or []
            if payload.get("anomaly"):
                alerts = list(alerts) + [str(payload.get("anomaly"))]
            if alerts:
                return AttentionDecision(
                    wake_cognition=True,
                    salience=SalienceLevel.URGENT.value,
                    reason=f"environmental alerts detected: {alerts}",
                )
            # Check for critical anomalies (e.g., disk < 2GB)
            disk_gb = payload.get("disk_free_gb")
            if disk_gb is not None and float(disk_gb) < 2.0:
                return AttentionDecision(
                    wake_cognition=True,
                    salience=SalienceLevel.URGENT.value,
                    reason="critical low disk space",
                )
            if event.salience >= self.wake_threshold:
                return AttentionDecision(
                    wake_cognition=True,
                    salience=event.salience,
                    reason="high-salience sensory observation",
                )
            return AttentionDecision(
                wake_cognition=False,
                salience=SalienceLevel.PASSIVE.value,
                reason="routine environmental telemetry",
            )

        # 4. Tool Execution Events
        if etype == EventType.TOOL_FAILED.value:
            is_critical = bool(payload.get("critical", False))
            salience = 0.85 if is_critical else 0.5
            return AttentionDecision(
                wake_cognition=salience >= self.wake_threshold,
                salience=salience,
                reason=f"tool execution failed: {payload.get('tool')}",
            )

        # 5. Background Task Completion
        if etype == EventType.BACKGROUND_COMPLETED.value:
            requires_followup = bool(payload.get("requires_followup", False))
            return AttentionDecision(
                wake_cognition=requires_followup,
                salience=0.75 if requires_followup else 0.4,
                reason="background task completion",
            )

        # Default: compare event's own salience with threshold
        event_salience = float(event.salience)
        return AttentionDecision(
            wake_cognition=event_salience >= self.wake_threshold,
            salience=event_salience,
            reason=f"event salience threshold comparison ({event_salience:.2f})",
        )
