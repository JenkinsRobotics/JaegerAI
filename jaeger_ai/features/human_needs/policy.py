"""Human Flourishing policy boundaries (single authoritative owner).

Invariants:
- Gentle nudges only; quiet hours default to 22:00-07:00.
- Needs never pause or outrank an active user task.
- Never contact third parties on the user's behalf without explicit authorization.
- Never manufacture psychological diagnoses; keep objective measures, user
  preferences, and inferred opportunities strictly separated.
- Belonging / self-transcendence prompts default to a daily digest rather than
  interrupting live work.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

DEFAULT_QUIET_START_HOUR = 22
DEFAULT_QUIET_END_HOUR = 7


class FlourishingDimension(str, Enum):
    """Six dimensions of the Human Flourishing Model (conceptual guide, not a rigid ladder)."""
    PHYSICAL_WELLBEING = "physical_wellbeing"
    SECURITY = "security"
    BELONGING = "belonging"
    COMPETENCE_ESTEEM = "competence_esteem"
    SELF_ACTUALIZATION = "self_actualization"
    SELF_TRANSCENDENCE = "self_transcendence"


class SignalKind(str, Enum):
    """Epistemic separation between measurable reality, stated preferences, and inferences."""
    OBJECTIVE_MEASURE = "objective_measure"
    USER_PREFERENCE = "user_preference"
    INFERRED_OPPORTUNITY = "inferred_opportunity"


DIGEST_ONLY_DIMENSIONS = frozenset({
    FlourishingDimension.BELONGING,
    FlourishingDimension.SELF_TRANSCENDENCE,
})


@dataclass(frozen=True)
class NudgeDecision:
    """Deterministic delivery policy for a proposed human-needs nudge."""
    deliver: str  # "gentle_nudge" | "daily_digest" | "suppress"
    reason: str
    pause_active_task: bool = False
    allow_third_party_contact: bool = False


def is_quiet_hours(
    now: datetime | None = None,
    *,
    quiet_start_hour: int = DEFAULT_QUIET_START_HOUR,
    quiet_end_hour: int = DEFAULT_QUIET_END_HOUR,
) -> bool:
    """True when local clock falls within quiet hours (default 22:00-07:00)."""
    dt = now or datetime.now()
    hour = dt.hour
    if quiet_start_hour > quiet_end_hour:
        return hour >= quiet_start_hour or hour < quiet_end_hour
    return quiet_start_hour <= hour < quiet_end_hour


def evaluate_nudge(
    dimension: FlourishingDimension | str,
    *,
    active_task_running: bool = False,
    now: datetime | None = None,
    contacts_third_party: bool = False,
    user_authorized_contact: bool = False,
    quiet_start_hour: int = DEFAULT_QUIET_START_HOUR,
    quiet_end_hour: int = DEFAULT_QUIET_END_HOUR,
) -> NudgeDecision:
    """Decide whether and how a human-needs suggestion may be surfaced."""
    dim = FlourishingDimension(dimension) if isinstance(dimension, str) else dimension
    if contacts_third_party and not user_authorized_contact:
        return NudgeDecision(
            deliver="suppress",
            reason="third-party contact requires explicit user authorization",
            pause_active_task=False,
            allow_third_party_contact=False,
        )
    if active_task_running:
        return NudgeDecision(
            deliver="daily_digest",
            reason="active task is running; human-needs prompts never interrupt or pause tasks",
            pause_active_task=False,
            allow_third_party_contact=bool(contacts_third_party and user_authorized_contact),
        )
    if is_quiet_hours(now, quiet_start_hour=quiet_start_hour, quiet_end_hour=quiet_end_hour):
        return NudgeDecision(
            deliver="daily_digest",
            reason="quiet hours (22:00-07:00); deferred to daily digest",
            pause_active_task=False,
            allow_third_party_contact=bool(contacts_third_party and user_authorized_contact),
        )
    if dim in DIGEST_ONLY_DIMENSIONS:
        return NudgeDecision(
            deliver="daily_digest",
            reason=f"{dim.value} suggestions route to the daily digest",
            pause_active_task=False,
            allow_third_party_contact=bool(contacts_third_party and user_authorized_contact),
        )
    return NudgeDecision(
        deliver="gentle_nudge",
        reason="permitted gentle nudge",
        pause_active_task=False,
        allow_third_party_contact=bool(contacts_third_party and user_authorized_contact),
    )
