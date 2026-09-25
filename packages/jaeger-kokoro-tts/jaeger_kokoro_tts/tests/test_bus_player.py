"""The speaker seam: audio goes onto a topic, not into a device.

This module no longer opens the output stream. It publishes
/act/speaker/pcm and `jaeger_os.nodes.audio_io` plays it — which is
what lets the chimes share the same speaker, and what gives the echo
canceller the played audio for free.

The interesting half is what publishing COSTS: this player no longer
knows when audio finished, because it no longer owns the device that
finishes it. The driver says so on /act/speaker/state.
"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from jaeger_os.transport import InProcBus, topics

from jaeger_kokoro_tts.bus_player import BusPlayer


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _player(bus, **kw):
    p = BusPlayer(bus=bus, samplerate=24000, **kw)
    p.start()
    time.sleep(0.15)
    return p


def _wait(predicate, timeout=3.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _drained(bus):
    bus.publish(topics.SpeakerState(state="idle"))


# ── audio goes out as messages ───────────────────────────────────

def test_enqueued_audio_is_published(bus):
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    p = _player(bus)
    try:
        p.enqueue(np.full(1200, 0.3, dtype=np.float32))
        assert _wait(lambda: got)
        msg = got[0]
        assert np.allclose(np.frombuffer(msg.samples, dtype=np.float32), 0.3)
        assert msg.sample_rate == 24000, "the driver resamples from this"
        assert msg.channels == 1
    finally:
        p.close()


def test_pcm_and_drain_are_correlated_to_one_utterance(bus):
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    p = _player(bus)
    try:
        p.begin("speech-42")
        p.enqueue(np.zeros(240, dtype=np.float32))
        assert _wait(lambda: got)
        assert got[0].correlation_id == "speech-42"

        # A notification finishing on the shared speaker must not complete
        # this speech request.
        bus.publish(topics.SpeakerState(
            state="idle", correlation_id="notification-7",
        ))
        time.sleep(0.15)
        assert not p._idle.is_set()

        bus.publish(topics.SpeakerState(
            state="idle", correlation_id="speech-42",
        ))
        assert _wait(p._idle.is_set)
    finally:
        p.close()


def test_empty_chunks_are_dropped(bus):
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    p = _player(bus)
    try:
        p.enqueue(None)
        p.enqueue(np.zeros(0, dtype=np.float32))
        time.sleep(0.3)
        assert got == []
    finally:
        p.close()


def test_a_non_float32_chunk_is_converted(bus):
    """Kokoro yields float32, but the contract is float32 PCM and a
    float64 chunk would put twice the bytes on the wire and play at
    half speed."""
    got = []
    bus.subscribe(topics.ACT_SPEAKER_PCM, got.append)
    p = _player(bus)
    try:
        p.enqueue(np.full(100, 0.5, dtype=np.float64))
        assert _wait(lambda: got)
        assert np.frombuffer(got[0].samples, dtype=np.float32).size == 100
    finally:
        p.close()


# ── "finished sending" is not "finished playing" ─────────────────

def test_drain_waits_for_the_device_not_the_send(bus):
    """The distinction /act/speaker/state exists for. A player that
    owned its stream could watch its own queue empty; one that
    publishes has to be told."""
    p = _player(bus)
    try:
        p.enqueue(np.zeros(24000, dtype=np.float32))   # 1 second
        p.mark_end()

        done = threading.Event()
        threading.Thread(
            target=lambda: (p.wait_until_drained(timeout=5), done.set()),
            daemon=True).start()

        time.sleep(0.3)
        assert not done.is_set(), "returned before the device finished"

        _drained(bus)
        assert done.wait(timeout=3), "never noticed the drain signal"
    finally:
        p.close()


def test_drain_returns_immediately_when_nothing_was_sent(bus):
    p = _player(bus)
    try:
        t0 = time.perf_counter()
        assert p.wait_until_drained(timeout=5)
        assert time.perf_counter() - t0 < 0.5
    finally:
        p.close()


def test_a_missing_driver_times_out_instead_of_hanging(bus, capfd):
    """Publishing to a topic nobody consumes SUCCEEDS. Without a bound
    on this wait, one missing driver hangs every speak() call forever —
    the same silent-failure class the mic side guards against."""
    p = _player(bus)
    try:
        p.enqueue(np.zeros(2400, dtype=np.float32))    # 0.1s of audio
        p.mark_end()
        t0 = time.perf_counter()
        assert p.wait_until_drained(timeout=30) is False
        elapsed = time.perf_counter() - t0
        assert elapsed < 12, f"hung for {elapsed:.1f}s waiting on nobody"
        err = capfd.readouterr().err
        assert "audio_io" in err, "the warning must name the missing driver"
    finally:
        p.close()


def test_correlated_speaker_error_fails_the_drain_immediately(bus):
    p = _player(bus)
    try:
        p.begin("speech-5")
        p.enqueue(np.zeros(24000, dtype=np.float32))
        bus.publish(topics.SpeakerState(
            state="error",
            error="output device disconnected",
            correlation_id="speech-5",
        ))
        started = time.perf_counter()
        assert p.wait_until_drained(timeout=10.0) is False
        assert time.perf_counter() - started < 1.0
        assert p.last_error == "output device disconnected"
    finally:
        p.close()


# ── barge-in ─────────────────────────────────────────────────────

def test_cancel_tells_the_driver_to_drop_queued_audio(bus):
    """Stopping synthesis is not enough: the sentence already published
    is on its way to the device, and that half-second is what makes an
    assistant feel deaf when you talk over it."""
    stops = []
    bus.subscribe(topics.ACT_SPEAKER_STOP, stops.append)
    p = _player(bus)
    try:
        p.enqueue(np.zeros(48000, dtype=np.float32))
        p.cancel()
        assert _wait(lambda: stops), "barge-in never reached the driver"
        assert p.wait_until_drained(timeout=1), \
            "cancel must leave the player idle, not waiting"
    finally:
        p.close()


# ── lifecycle ────────────────────────────────────────────────────

def test_close_stops_listening(bus):
    p = _player(bus)
    p.enqueue(np.zeros(240, dtype=np.float32))
    p.close()
    assert not p.is_open()
    _drained(bus)          # must not raise into a closed player
    time.sleep(0.2)


def test_start_is_idempotent(bus):
    p = _player(bus)
    try:
        p.start()
        p.start()
        assert p.is_open()
    finally:
        p.close()


def test_it_reports_a_bus_destination_not_a_device(bus):
    """The engine prints this at open and puts it in its result dicts;
    naming a device that does not exist would be a lie in a log."""
    p = _player(bus)
    try:
        assert "speaker" in p.device_name
        assert p.device_index is None
    finally:
        p.close()
