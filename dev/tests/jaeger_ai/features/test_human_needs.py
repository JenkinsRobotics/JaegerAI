from datetime import datetime, timedelta

from jaeger_ai.features.human_needs import DeliveryState, Message, Signals, decide_delivery, evaluate


NOW = datetime(2026, 11, 1, 15)


def test_priority_and_unknown_signals():
    assert evaluate(Signals(), NOW) == ()
    found = evaluate(Signals(aqi=151, hydration_logged_today=0, work_stretch_hours=4,
                             co_detected=True, days_since_plan_with_people=3,
                             days_since_own_project_time=3), NOW)
    assert [message.need for message in found] == ["air", "water", "food_and_sleep", "safety", "connection", "purpose"]


def test_thresholds_and_no_food_claim():
    assert evaluate(Signals(aqi=150, hydration_logged_today=1, usual_hydration=4,
                            sleep_hours_last_night=5, work_stretch_hours=3.9), NOW) == ()
    found = evaluate(Signals(hydration_logged_today=1, usual_hydration=4,
                             sleep_hours_last_night=4.9), NOW.replace(hour=18))
    assert [message.need for message in found] == ["water", "food_and_sleep"]
    assert "skipped a meal" not in " ".join(message.text for message in found)


def test_safety_breaks_quiet_hours_and_repeats_until_cleared():
    night = NOW.replace(hour=23)
    found = evaluate(Signals(co_detected=True, smoke_detected=True, leak_detected=True,
                             emergency_alert=True, aqi=200), night)
    assert [message.alert_id for message in decide_delivery(found, night, DeliveryState())] == ["co", "smoke", "leak", "emergency"]
    state = DeliveryState(last_safety_at={"co": night}, safety_snoozed_until={"co": night + timedelta(hours=1)})
    assert not any(message.alert_id == "co" for message in decide_delivery(found, night + timedelta(minutes=4), state))
    assert any(message.alert_id == "co" for message in decide_delivery(found, night + timedelta(minutes=5), state))
    assert evaluate(Signals(co_detected=False), night) == ()


def test_quiet_hours_hold_nudges_and_digests():
    found = evaluate(Signals(aqi=151, days_since_plan_with_people=3), NOW)
    assert decide_delivery(found, NOW.replace(hour=22), DeliveryState()) == ()
    assert len(decide_delivery(found, NOW.replace(hour=7), DeliveryState())) == 2


def test_nudge_snooze_and_four_hour_cooldown():
    found = evaluate(Signals(aqi=151), NOW)
    state = DeliveryState(last_nudge={"air": NOW}, snoozed_until={"air": NOW + timedelta(hours=1)})
    assert decide_delivery(found, NOW + timedelta(hours=1), state) == ()
    assert decide_delivery(found, NOW + timedelta(hours=3, minutes=59), state) == ()
    assert decide_delivery(found, NOW + timedelta(hours=4), state) == found


def test_digest_only_once_per_day():
    found = evaluate(Signals(days_since_plan_with_people=3, days_since_own_project_time=3), NOW)
    assert all(message.kind == "digest" for message in found)
    assert decide_delivery(found, NOW, DeliveryState(last_digest_at=NOW - timedelta(days=1))) == found
    assert decide_delivery(found, NOW, DeliveryState(last_digest_at=NOW)) == ()


def test_only_messages_for_matthew_no_actions():
    found = evaluate(Signals(co_detected=True, days_since_plan_with_people=3), NOW)
    assert all(isinstance(message, Message) for message in found)
    assert set(Message.__dataclass_fields__) == {"need", "kind", "text", "alert_id"}
