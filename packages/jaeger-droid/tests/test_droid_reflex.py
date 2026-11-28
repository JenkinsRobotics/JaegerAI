"""Tests for DroidReflexController privacy auto-park & presence reflexes."""

from __future__ import annotations

from jaeger_droid import DroidReflexController, HostDroidEmbodiment


def test_droid_reflex_auto_park_and_touch() -> None:
    awake = {"val": True}
    events: list[tuple[str, dict]] = []

    def _sleep() -> None:
        awake["val"] = False

    reflex = DroidReflexController(
        is_awake=lambda: awake["val"],
        is_estop=lambda: False,
        sleep_fn=_sleep,
        on_event=lambda ev, payload: events.append((ev, dict(payload))),
        auto_park_enabled=True,
        idle_park_s=120.0,
    )
    t0 = 1000.0
    reflex.touch("wake", now=t0)

    # Within idle window -> stays awake
    r1 = reflex.evaluate_once(now=t0 + 60.0)
    assert r1["acted"] is False and awake["val"] is True

    # Touch resets idle timer
    reflex.touch("voice_clip", now=t0 + 90.0)
    r2 = reflex.evaluate_once(now=t0 + 180.0)
    assert r2["acted"] is False and awake["val"] is True

    # Past idle threshold -> auto-parks & emits event
    r3 = reflex.evaluate_once(now=t0 + 215.0)
    assert r3["acted"] is True and r3["action"] == "auto_park_sleep"
    assert awake["val"] is False
    assert len(events) == 1 and events[0][0] == "droid.auto_parked"

    # Already asleep -> no-op
    r4 = reflex.evaluate_once(now=t0 + 400.0)
    assert r4["acted"] is False and r4["reason"] == "already_asleep"


def test_host_droid_exposes_reflex_in_observe() -> None:
    droid = HostDroidEmbodiment(probe_on_init=False)
    obs = droid.observe()
    assert "reflex" in obs
    assert obs["reflex"]["auto_park_enabled"] is True
    updated = droid.reflex.update_config(auto_park_enabled=False, idle_park_s=180.0)
    assert updated["auto_park_enabled"] is False
    assert updated["idle_park_s"] == 180
