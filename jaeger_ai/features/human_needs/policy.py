"""Pure, local-snapshot human-needs rules. No source or delivery adapters."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Mapping

Need = Literal["air", "water", "food_and_sleep", "safety", "connection", "purpose"]
Kind = Literal["safety_alert", "nudge", "digest"]
NEEDS: tuple[Need, ...] = (
    "air", "water", "food_and_sleep", "safety", "connection", "purpose"
)


@dataclass(frozen=True)
class Signals:
    aqi: int | None = None
    co_detected: bool | None = None
    smoke_detected: bool | None = None
    leak_detected: bool | None = None
    emergency_alert: bool | None = None
    hydration_logged_today: float | None = None
    usual_hydration: float | None = None
    sleep_hours_last_night: float | None = None
    work_stretch_hours: float | None = None
    days_since_plan_with_people: float | None = None
    days_since_own_project_time: float | None = None


@dataclass(frozen=True)
class Message:
    need: Need
    kind: Kind
    text: str
    alert_id: str | None = None


@dataclass(frozen=True)
class DeliveryState:
    """Caller-held timestamps; the library never persists or sends anything."""

    last_nudge: Mapping[Need, datetime] = field(default_factory=dict)
    snoozed_until: Mapping[Need, datetime] = field(default_factory=dict)
    last_digest_at: datetime | None = None
    last_safety_at: Mapping[str, datetime] = field(default_factory=dict)
    safety_snoozed_until: Mapping[str, datetime] = field(default_factory=dict)


def evaluate(signals: Signals, now: datetime) -> tuple[Message, ...]:
    """Return unmet needs in priority order; absent signals are unknown."""
    messages: list[Message] = []
    if signals.aqi is not None and signals.aqi >= 151:
        messages.append(Message("air", "nudge", f"Air quality outside is poor (AQI {signals.aqi}). Maybe keep windows closed."))
    if signals.hydration_logged_today is not None:
        if now.hour >= 14 and signals.hydration_logged_today == 0:
            messages.append(Message("water", "nudge", "Haven't seen any water logged yet today. Maybe grab a glass?"))
        elif (now.hour >= 18 and signals.usual_hydration is not None
              and signals.usual_hydration > 0
              and signals.hydration_logged_today < signals.usual_hydration / 2):
            messages.append(Message("water", "nudge", "Your water log is below half your usual amount today. Maybe grab a glass?"))
    if ((signals.sleep_hours_last_night is not None and signals.sleep_hours_last_night < 5)
            or (signals.work_stretch_hours is not None and signals.work_stretch_hours >= 4)):
        messages.append(Message("food_and_sleep", "nudge", "You've been at it a while. Maybe eat something or take a short break."))
    for signal, alert_id, text in (
        (signals.co_detected, "co", "CO detected. Get to fresh air now."),
        (signals.smoke_detected, "smoke", "Smoke detected at home. Check it now."),
        (signals.leak_detected, "leak", "Water leak detected at home. Check it now."),
        (signals.emergency_alert, "emergency", "Emergency alert for your area. Check it now."),
    ):
        if signal is True:
            messages.append(Message("safety", "safety_alert", text, alert_id))
    if signals.days_since_plan_with_people is not None and signals.days_since_plan_with_people >= 3:
        messages.append(Message("connection", "digest", "It's been a few days since a plan with someone. Anyone you'd like to catch up with?"))
    if signals.days_since_own_project_time is not None and signals.days_since_own_project_time >= 3:
        messages.append(Message("purpose", "digest", "Want to block some time this week for something you care about?"))
    return tuple(messages)


def decide_delivery(messages: tuple[Message, ...], now: datetime, state: DeliveryState) -> tuple[Message, ...]:
    """Select messages due now; caller records actual deliveries in state."""
    quiet = now.hour >= 22 or now.hour < 7
    due: list[Message] = []
    digest: list[Message] = []
    for message in messages:
        if message.kind == "safety_alert":
            if message.alert_id is None:
                continue
            # A request longer than five minutes cannot delay a safety repeat.
            last = state.last_safety_at.get(message.alert_id)
            snooze = state.safety_snoozed_until.get(message.alert_id)
            if last is not None and now - last < timedelta(minutes=5):
                continue
            if snooze is not None and last is not None and now < min(snooze, last + timedelta(minutes=5)):
                continue
            due.append(message)
        elif message.kind == "nudge":
            if quiet or message.need in ("connection", "purpose"):
                continue
            last = state.last_nudge.get(message.need)
            snooze = state.snoozed_until.get(message.need)
            if last is not None and now - last < timedelta(hours=4):
                continue
            if snooze is not None and last is not None and now < min(snooze, last + timedelta(hours=1)):
                continue
            due.append(message)
        elif message.kind == "digest" and message.need in ("connection", "purpose"):
            digest.append(message)
    if not quiet and (state.last_digest_at is None or state.last_digest_at.date() < now.date()):
        due.extend(digest)
    return tuple(due)
