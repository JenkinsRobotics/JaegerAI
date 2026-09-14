"""The mic seam: audio arrives on a topic, not from a device.

This module no longer opens the microphone. `jaeger_os.nodes.audio_io`
owns the device and publishes echo-cancelled frames; `_MicStream`
subscribes. These tests cover the seam itself — including the failure
mode the split introduced, which is that subscribing to a topic nobody
publishes SUCCEEDS.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from jaeger_os.transport import InProcBus, topics

from jaeger_whisper_stt.engine._base import _MicStream

FRAME = 160


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _mic(bus, **kw):
    return _MicStream(bus=bus, sample_rate=16000, frame_samples=FRAME, **kw)


def _publish(bus, value=0.5, n=FRAME):
    bus.publish(topics.AudioInFrame(
        samples=np.full(n, value, dtype=np.float32).tobytes(),
        sample_rate=16000, channels=1))


def _wait(predicate, timeout=3.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── frames off the bus ───────────────────────────────────────────

def test_a_published_frame_reaches_the_queue(bus):
    mic = _mic(bus)
    mic.start()
    try:
        time.sleep(0.15)
        _publish(bus, 0.25)
        assert _wait(lambda: not mic.q.empty())
        chunk = mic.q.get_nowait()
        assert chunk.shape == (FRAME, 1), "the VAD reads (N, 1)-shaped frames"
        assert np.allclose(chunk, 0.25)
    finally:
        mic.stop()


def test_a_partial_block_is_buffered_until_complete(bus):
    """Half a VAD block is carried; incomplete audio never leaks downstream."""
    mic = _mic(bus)
    mic.start()
    try:
        time.sleep(0.15)
        _publish(bus, n=FRAME // 2)
        time.sleep(0.3)
        assert mic.q.empty()
    finally:
        mic.stop()


# ── pause is LOCAL now ───────────────────────────────────────────

def test_pausing_drops_frames_without_touching_the_device(bus):
    """Pause used to stop the input stream. A shared microphone cannot
    honour that — one consumer pausing would starve every other
    subscriber — so a paused stream discards on arrival instead."""
    mic = _mic(bus)
    other_consumer = []
    bus.subscribe(topics.SENSE_MIC_PCM, other_consumer.append)
    mic.start()
    try:
        time.sleep(0.15)
        mic.set_paused(True)
        _publish(bus)
        assert _wait(lambda: other_consumer), \
            "pausing one consumer stopped the whole device"
        assert mic.q.empty(), "a paused stream queued audio anyway"
    finally:
        mic.stop()


def test_unpausing_drops_the_stale_backlog(bus):
    mic = _mic(bus)
    mic.start()
    try:
        time.sleep(0.15)
        _publish(bus)
        assert _wait(lambda: not mic.q.empty())
        mic.set_paused(True)
        mic.set_paused(False)
        assert mic.q.empty(), "audio from before the pause is stale"
    finally:
        mic.stop()


def test_a_full_queue_keeps_the_newest_audio(bus):
    """A backed-up VAD should work on recent audio, not grind through a
    backlog from seconds ago."""
    mic = _mic(bus, max_queue_frames=3)
    mic.start()
    try:
        time.sleep(0.15)
        for i in range(10):
            _publish(bus, value=float(i))
        assert _wait(lambda: mic.q.qsize() == 3)
        kept = [mic.q.get_nowait()[0, 0] for _ in range(3)]
        assert kept == [7.0, 8.0, 9.0], f"kept stale frames: {kept}"
        health = mic.health()
        assert health["frames_dropped"] == 7
        assert health["queue_capacity"] == 3
    finally:
        mic.stop()


# ── the failure mode the split introduced ────────────────────────

def test_a_silent_topic_is_reported(bus, capfd, monkeypatch):
    """THE risk of moving the device behind a topic: subscribing to
    something nobody publishes SUCCEEDS. Without this warning the
    symptom is an agent that never hears you, reports healthy, and logs
    nothing — strictly worse than the OSError a missing device used to
    raise."""
    from jaeger_whisper_stt.engine import _base
    monkeypatch.setattr(_base, "LIVENESS_TIMEOUT_S", 0.2)

    mic = _mic(bus)          # nothing is publishing /sense/mic/pcm
    mic.start()
    try:
        time.sleep(0.5)
        err = capfd.readouterr().err
        assert "no audio" in err
        assert "audio_io" in err, "the warning must name the missing driver"
    finally:
        mic.stop()


def test_a_live_topic_stays_quiet(bus, capfd, monkeypatch):
    """The guard must not cry wolf at a working system."""
    from jaeger_whisper_stt.engine import _base
    monkeypatch.setattr(_base, "LIVENESS_TIMEOUT_S", 0.3)

    mic = _mic(bus)
    mic.start()
    try:
        time.sleep(0.1)
        _publish(bus)
        time.sleep(0.5)
        assert "no audio" not in capfd.readouterr().err
    finally:
        mic.stop()


def test_stopping_cancels_the_pending_warning(bus, capfd, monkeypatch):
    """A session torn down before the timeout must not warn afterwards
    about a topic it is no longer listening to."""
    from jaeger_whisper_stt.engine import _base
    monkeypatch.setattr(_base, "LIVENESS_TIMEOUT_S", 0.4)

    mic = _mic(bus)
    mic.start()
    mic.stop()
    time.sleep(0.6)
    assert "no audio" not in capfd.readouterr().err


# ── it stops consuming when told ─────────────────────────────────

def test_stop_unsubscribes(bus):
    mic = _mic(bus)
    mic.start()
    time.sleep(0.15)
    mic.stop()
    _publish(bus)
    time.sleep(0.3)
    assert mic.q.empty(), "still receiving audio after stop()"


# ── frame-size regrouping ────────────────────────────────────────
#
# The bug these pin: jaeger_os's audio_io publishes 10 ms frames (160
# samples — speexdsp's AEC needs fixed equal-length near/far frames)
# while the continuous pipeline's VAD wants 30 ms (480). _MicStream
# used to DROP every frame that was not an exact match, so the mic
# meter moved, the driver was healthy, and the STT heard nothing.

def test_small_frames_are_regrouped_not_dropped(bus):
    """3x160 in -> exactly one 480 block out. Nothing lost."""
    mic = _MicStream(bus=bus, sample_rate=16000, frame_samples=480)
    mic.start()
    try:
        for _ in range(3):
            _publish(bus, value=0.25, n=160)
        assert _wait(lambda: mic.q.qsize() >= 1), "regrouping never fired"
        block = mic.q.get_nowait()
        assert block.shape == (480, 1)
        assert np.allclose(block, 0.25)      # the audio itself survives
        assert mic.q.empty()                 # and no partial block leaks
    finally:
        mic.stop()


def test_large_frames_split_into_blocks(bus):
    """The other direction: 1x960 in -> 2x480 out."""
    mic = _MicStream(bus=bus, sample_rate=16000, frame_samples=480)
    mic.start()
    try:
        _publish(bus, value=0.5, n=960)
        assert _wait(lambda: mic.q.qsize() >= 2)
        assert mic.q.get_nowait().shape == (480, 1)
        assert mic.q.get_nowait().shape == (480, 1)
    finally:
        mic.stop()


def test_a_remainder_is_carried_not_discarded(bus):
    """500 samples = one block plus 20 carried. The next frame
    completes it — dropping the tail would clip every utterance."""
    mic = _MicStream(bus=bus, sample_rate=16000, frame_samples=480)
    mic.start()
    try:
        _publish(bus, value=0.5, n=500)
        assert _wait(lambda: mic.q.qsize() >= 1)
        mic.q.get_nowait()
        _publish(bus, value=0.5, n=460)      # 20 carried + 460 = 480
        assert _wait(lambda: mic.q.qsize() >= 1), "the remainder was dropped"
    finally:
        mic.stop()


def test_a_rate_mismatch_is_still_refused(bus, capfd):
    """Regrouping fixes SIZE. Rate needs resampling, which this class
    must not do silently — that stays a loud wiring error."""
    mic = _MicStream(bus=bus, sample_rate=16000, frame_samples=480)
    mic.start()
    try:
        for _ in range(4):
            bus.publish(topics.AudioInFrame(
                samples=np.zeros(480, dtype=np.float32).tobytes(),
                sample_rate=48000, channels=1))
        time.sleep(0.2)
        assert mic.q.empty()
        err = capfd.readouterr().err
        assert "48000" in err
        assert err.count("ignoring") == 1     # once, not per frame
    finally:
        mic.stop()


def test_malformed_pcm_is_counted_without_killing_the_subscription(bus):
    mic = _mic(bus)
    mic.start()
    try:
        bus.publish(topics.AudioInFrame(
            samples=b"not-float32", sample_rate=16000, channels=1,
        ))
        assert _wait(lambda: mic.health()["invalid_frames"] == 1)
        _publish(bus, value=0.1)
        assert _wait(lambda: mic.health()["frames_valid"] == 1)
        health = mic.health()
        assert health["receiving"] is True
        assert health["last_error"]
    finally:
        mic.stop()
