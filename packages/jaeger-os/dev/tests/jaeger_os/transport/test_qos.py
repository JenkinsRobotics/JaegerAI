"""Per-topic delivery policy.

Parity gap 3b. Before this, every topic got identical treatment: a
3.6 MB video frame and a 200-byte e-stop shared one queue policy at one
depth. That is wrong in both directions — a dropped frame is fine
because the next is along in 33 ms and is more current, while a dropped
e-stop is a robot that does not stop.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.contract.qos import (
    BEST_EFFORT, DEFAULT_QOS, RELIABLE, Qos, qos_for,
)
from jaeger_os.transport import InProcBus, topics


# ── the policy itself ────────────────────────────────────────────

def test_an_unlisted_topic_gets_the_default():
    assert qos_for("/act/never_declared") is DEFAULT_QOS


def test_stop_commands_are_reliable():
    """The messages where losing one is a safety event."""
    for topic in (topics.ACT_ESTOP_TRIGGER, topics.ACT_SPEECH_STOP,
                  topics.ACT_DISPLAY_STOP):
        assert qos_for(topic).reliability == RELIABLE, topic


def test_frames_keep_only_the_newest():
    """A renderer that falls behind should show the NEWEST frame, not
    work through stale ones. Buffering 64 video frames is 230 MB of
    latency nobody wants to watch."""
    for topic in (topics.ACT_DISPLAY_FRAME, topics.ACT_DISPLAY_FRAME,
                  topics.SENSE_CAMERA_IMAGE_RAW):
        q = qos_for(topic)
        assert q.depth <= 2, topic
        assert q.reliability == BEST_EFFORT, topic


def test_a_frame_is_not_treated_like_an_estop():
    """The whole point of the gap, in one assertion."""
    frame = qos_for(topics.ACT_DISPLAY_FRAME)
    estop = qos_for(topics.ACT_ESTOP_TRIGGER)
    assert frame.depth != estop.depth
    assert frame.reliability != estop.reliability


def test_a_bad_policy_is_refused_at_construction():
    with pytest.raises(ValueError, match="depth"):
        Qos(depth=0)
    with pytest.raises(ValueError, match="reliability"):
        Qos(reliability="eventually")


# ── the bus honours it ───────────────────────────────────────────

def test_subscriptions_are_sized_by_topic_policy():
    bus = InProcBus()
    try:
        bus.subscribe(topics.ACT_DISPLAY_FRAME, lambda m: None)
        bus.subscribe(topics.ACT_ESTOP_TRIGGER, lambda m: None)
        stats = bus.stats()
        assert stats[topics.ACT_DISPLAY_FRAME]["depth"] == 2
        assert stats[topics.ACT_ESTOP_TRIGGER]["depth"] == 256
        assert stats[topics.ACT_ESTOP_TRIGGER]["reliability"] == RELIABLE
    finally:
        bus.close()


def test_a_shallow_frame_queue_keeps_the_newest(caplog):
    """A wedged renderer must end up showing recent frames, not a
    backlog from seconds ago."""
    gate = threading.Event()
    seen = []

    def wedged(msg):
        gate.wait(timeout=5.0)
        seen.append(msg)

    bus = InProcBus()
    try:
        bus.subscribe(topics.ACT_DISPLAY_FRAME, wedged)
        time.sleep(0.1)
        for i in range(40):
            bus.publish(topics.DisplayFrame(width=1, height=1, seq=i))
        time.sleep(0.2)
        stats = bus.stats()[topics.ACT_DISPLAY_FRAME]
        assert stats["dropped"] > 30, "a depth-2 queue should shed heavily"
        gate.set()
        time.sleep(0.3)
        # Whatever survived must be from the END of the burst.
        assert seen, "nothing was delivered at all"
        assert max(f.seq for f in seen) > 30, "kept stale frames, not new"
    finally:
        gate.set()
        bus.close()


def test_a_reliable_topic_buffers_deeply_instead_of_shedding():
    """256 deep: a burst of control messages is absorbed where a
    depth-2 frame queue would have shed almost all of it."""
    seen = []
    bus = InProcBus()
    try:
        bus.subscribe(topics.ACT_DISPLAY_STOP,
                      lambda m: (time.sleep(0.001), seen.append(m)))
        time.sleep(0.1)
        for _ in range(100):
            bus.publish(topics.DisplayStop())
        deadline = time.perf_counter() + 5.0
        while len(seen) < 100 and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert len(seen) == 100, f"lost {100 - len(seen)} stop commands"
        assert bus.stats()[topics.ACT_DISPLAY_STOP]["dropped"] == 0
    finally:
        bus.close()


def test_a_reliable_overflow_is_impossible_to_miss(capfd):
    """We still cannot block the publisher without recreating the
    coupling per-subscriber queues removed — so on a RELIABLE topic the
    message is lost either way. What changes is that it screams."""
    gate = threading.Event()
    bus = InProcBus(maxsize=1)          # force overflow deterministically
    try:
        bus.subscribe(topics.ACT_ESTOP_TRIGGER, lambda m: gate.wait(timeout=5.0))
        time.sleep(0.1)
        for _ in range(20):
            bus.publish(topics.EStop())
        time.sleep(0.2)
        err = capfd.readouterr().err
        assert "RELIABLE" in err and "LOST" in err
        assert bus.stats()[topics.ACT_ESTOP_TRIGGER]["dropped"] > 0
    finally:
        gate.set()
        bus.close()


def test_an_explicit_maxsize_overrides_policy():
    """Tests need deterministic overflow; production should not use it."""
    bus = InProcBus(maxsize=3)
    try:
        bus.subscribe(topics.ACT_ESTOP_TRIGGER, lambda m: None)
        assert bus.stats()[topics.ACT_ESTOP_TRIGGER]["depth"] == 3
    finally:
        bus.close()


# ── instances inherit their class's policy ───────────────────────

def test_an_instance_path_inherits_its_canonical_policy():
    """The bug this closes was silent and backwards: an instanced frame
    topic took the 64-deep DEFAULT instead of its depth-2 policy, so a
    stalled subscriber buffered 64 frames — 230 MB at 720p — of stale
    pixels. It appeared the moment anyone used the instances the
    hierarchy shipped, which is to say immediately."""
    canon = qos_for(topics.ACT_DISPLAY_FRAME)
    for instance in ("face0", "media0", "matrix7"):
        live = qos_for(f"/act/display/{instance}/frame")
        assert live == canon, f"{instance} fell back to the default"
    assert canon.depth == 2


def test_an_instanced_stop_command_keeps_reliable():
    """Losing RELIABLE on an instance is a safety event, not a dropped
    update — the one place the fallback must not miss."""
    live = qos_for("/act/estop/unit0/trigger")
    assert live.reliability == RELIABLE
    assert live == qos_for(topics.ACT_ESTOP_TRIGGER)


def test_an_unknown_instance_class_still_gets_the_default():
    assert qos_for("/act/invented/inst0/thing") is DEFAULT_QOS
