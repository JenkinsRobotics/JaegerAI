"""Tests for AvatarAutoStateDriver — the bus subscriber that flips
Lilith's face emotion based on TTS lifecycle events.

Pipeline:
  /act/speech  → driver publishes /act/animation (emotion="speaking")
  /sense/spoken → driver publishes /act/animation (emotion="neutral")
"""

from __future__ import annotations

import time

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes.animation import AvatarAutoStateDriver
from jaeger_os.transport import InProcBus


@pytest.fixture
def captured():
    bus = InProcBus()
    received: list[topics.AnimationCommand] = []
    bus.subscribe(
        topics.ACT_ANIMATION,
        lambda msg: received.append(msg),
    )
    driver = AvatarAutoStateDriver(bus=bus)
    driver.start()
    yield bus, received, driver
    driver.stop()
    bus.close()


# ── speech start → speaking emotion ────────────────────────────────

def test_speech_command_triggers_speaking_emotion(captured) -> None:
    bus, received, _ = captured
    bus.publish(topics.SpeechCommand(text="hello"))
    for _ in range(20):
        if received:
            break
        time.sleep(0.02)
    assert len(received) == 1
    assert received[0].adapter == "math"
    assert received[0].params.get("emotion") == "speaking"


# ── speech done → neutral ──────────────────────────────────────────

def test_spoken_ack_triggers_neutral_emotion(captured) -> None:
    bus, received, _ = captured
    bus.publish(topics.SpokenAck(ok=True, duration_s=1.0))
    for _ in range(20):
        if received:
            break
        time.sleep(0.02)
    assert len(received) == 1
    assert received[0].params.get("emotion") == "neutral"


# ── full conversation cycle ────────────────────────────────────────

def test_speech_then_ack_cycles_emotions(captured) -> None:
    bus, received, _ = captured
    bus.publish(topics.SpeechCommand(text="testing"))
    time.sleep(0.05)
    bus.publish(topics.SpokenAck(ok=True, duration_s=0.5))
    for _ in range(20):
        if len(received) >= 2:
            break
        time.sleep(0.02)
    assert len(received) == 2
    assert received[0].params.get("emotion") == "speaking"
    assert received[1].params.get("emotion") == "neutral"


# ── start/stop idempotency ─────────────────────────────────────────

def test_start_is_idempotent() -> None:
    bus = InProcBus()
    driver = AvatarAutoStateDriver(bus=bus)
    driver.start()
    driver.start()  # second call no-op
    received: list[topics.AnimationCommand] = []
    bus.subscribe(topics.ACT_ANIMATION,
                   lambda msg: received.append(msg))
    bus.publish(topics.SpeechCommand(text="x"))
    time.sleep(0.1)
    # Only ONE animation command should fire — not two from a
    # double-subscribed driver.
    assert len(received) == 1
    driver.stop()
    bus.close()


def test_stop_then_start_works() -> None:
    bus = InProcBus()
    driver = AvatarAutoStateDriver(bus=bus)
    driver.start()
    driver.stop()
    driver.start()  # should re-subscribe
    received: list[topics.AnimationCommand] = []
    bus.subscribe(topics.ACT_ANIMATION,
                   lambda msg: received.append(msg))
    bus.publish(topics.SpeechCommand(text="x"))
    time.sleep(0.1)
    assert len(received) == 1
    driver.stop()
    bus.close()


# ── custom emotion targets ─────────────────────────────────────────

def test_custom_emotion_targets() -> None:
    """Operator can override the default emotion mapping
    (speaking_emotion, idle_emotion)."""
    bus = InProcBus()
    driver = AvatarAutoStateDriver(
        bus=bus,
        speaking_emotion="happy",
        idle_emotion="focused",
    )
    driver.start()
    received: list[topics.AnimationCommand] = []
    bus.subscribe(topics.ACT_ANIMATION,
                   lambda msg: received.append(msg))
    bus.publish(topics.SpeechCommand(text="x"))
    time.sleep(0.05)
    bus.publish(topics.SpokenAck(ok=True))
    for _ in range(20):
        if len(received) >= 2:
            break
        time.sleep(0.02)
    assert received[0].params.get("emotion") == "happy"
    assert received[1].params.get("emotion") == "focused"
    driver.stop()
    bus.close()
