"""Chimes go to the shared speaker, not a second output stream.

The earcons were the THIRD thing opening the audio device, alongside
Kokoro and (until the driver existed) Whisper's mic. They are also the
clearest example of the mechanism/policy split: whisper DETECTS the
wake phrase, the app DECIDES that deserves a beep (jaeger_ai's
voice_loop owns --no-chimes), and the driver plays it.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from jaeger_os.core.audio.chimes import CHIME_SAMPLE_RATE, ChimePlayer
from jaeger_os.transport import InProcBus, topics


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _wait(predicate, timeout=3.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_a_chime_is_published_not_played_locally(bus):
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    ChimePlayer(bus=bus).play("wake")
    assert _wait(lambda: got), "the chime never reached the speaker topic"
    msg = got[0]
    assert msg.sample_rate == CHIME_SAMPLE_RATE
    samples = np.frombuffer(msg.samples, dtype=np.float32)
    assert samples.size > 0 and np.any(samples), "published silence"


def test_both_earcons_are_distinct(bus):
    """wake is one tone, followup is two (low->high) — they mean
    different things to the user and must not sound the same."""
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    player = ChimePlayer(bus=bus)
    player.play("wake")
    player.play("followup")
    assert _wait(lambda: len(got) >= 2)
    a, b = (np.frombuffer(m.samples, dtype=np.float32) for m in got[:2])
    assert a.size != b.size or not np.allclose(a[:min(a.size, b.size)],
                                               b[:min(a.size, b.size)])


def test_policy_still_belongs_to_the_caller(bus):
    """--no-chimes is an APP flag. Publishing must not smuggle the
    decision into the framework."""
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    ChimePlayer(bus=bus, enabled=False).play("wake")
    ChimePlayer(bus=bus, wake_enabled=False).play("wake")
    time.sleep(0.3)
    assert got == [], "a disabled chime was published anyway"


def test_an_unknown_kind_is_ignored(bus):
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    ChimePlayer(bus=bus).play("nonsense")
    time.sleep(0.3)
    assert got == []


def test_publishing_does_not_block_for_the_tone(bus):
    """The device path blocked for the tone's duration plus a tail.
    Nothing needed that, and blocking here would mean waiting on a
    round trip to another node."""
    player = ChimePlayer(bus=bus)
    t0 = time.perf_counter()
    for _ in range(5):
        player.play("wake")
    assert time.perf_counter() - t0 < 0.1


def test_no_bus_keeps_the_local_device_path(bus):
    """Dev tools and benches run with no bus at all; they must still
    make a sound rather than silently no-op."""
    player = ChimePlayer()
    assert player.bus is None
    assert hasattr(player, "_play_via_avaudio")
