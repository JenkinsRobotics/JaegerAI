"""Tests for ``jaeger_os.nodes.software.audio_session`` — Track B.3.1.

Mock STT adapter so we don't load Whisper or open the mic.  The
real-Whisper integration runs out-of-band via
``./launch --stt-boot-test`` (Track B.3.2).
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os import topics
from jaeger_os.nodes import AudioSessionNode, STTNode
from jaeger_os.transport import InProcBus


# ── mock adapter ─────────────────────────────────────────────────

class _MockAdapter:
    """Drop-in for WhisperSTTContinuous's STT-shaped surface.

    Tests push phrases via ``feed_phrase`` to simulate Whisper
    finishing a transcription.  Records lifecycle calls so tests can
    verify setup/teardown ran.
    """

    def __init__(self):
        self.started = False
        self.stopped = False
        self.paused = []
        self.on_speech_detected = None
        self.drained = False
        self._phrases = []
        self._lock = threading.Lock()

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def next_phrase(self, timeout=1.0):
        # Tight poll loop bounded by `timeout` so tick() doesn't
        # block longer than the node's poll_timeout_s.
        deadline = time.monotonic() + (timeout or 0.0)
        while time.monotonic() < deadline:
            with self._lock:
                if self._phrases:
                    return self._phrases.pop(0)
            time.sleep(0.01)
        return None

    def set_paused(self, paused):
        self.paused.append(paused)

    def set_on_speech_detected(self, callback):
        self.on_speech_detected = callback

    def open_followup(self):
        pass

    def drain_pending(self):
        self.drained = True

    def feed_phrase(self, text: str):
        with self._lock:
            self._phrases.append(text)

    def fire_speech_start(self):
        if self.on_speech_detected is not None:
            self.on_speech_detected()


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _start_node(bus, adapter, **kwargs):
    node = AudioSessionNode(bus=bus, adapter=adapter, **kwargs)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)  # let setup() complete
    return node, thread


def _stop_node(node, thread):
    node.stop()
    thread.join(timeout=2.0)


# ── lifecycle ────────────────────────────────────────────────────

def test_setup_starts_adapter(bus):
    """The node's setup() calls adapter.start() to open the mic."""
    adapter = _MockAdapter()
    node, thread = _start_node(bus, adapter)
    try:
        assert adapter.started is True
    finally:
        _stop_node(node, thread)


def test_teardown_stops_adapter(bus):
    """The node's teardown() closes the adapter (mic) cleanly."""
    adapter = _MockAdapter()
    node, thread = _start_node(bus, adapter)
    _stop_node(node, thread)
    assert adapter.stopped is True


def test_adapter_stop_exception_doesnt_block_teardown(bus):
    """If adapter.stop() raises, the node's teardown logs and
    moves on — must not propagate."""
    class _BadStop(_MockAdapter):
        def stop(self):
            raise RuntimeError("mic stuck")
    adapter = _BadStop()
    node, thread = _start_node(bus, adapter)
    # Should not raise.
    _stop_node(node, thread)


# ── phrase publishing ────────────────────────────────────────────

def test_phrase_becomes_transcript_message(bus):
    """A phrase committed by the adapter triggers a /sense/transcript
    publish."""
    adapter = _MockAdapter()
    received = []
    event = threading.Event()

    def on_transcript(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
    node, thread = _start_node(bus, adapter, poll_timeout_s=0.1)
    try:
        adapter.feed_phrase("hello world")
        assert event.wait(timeout=2.0), "no /sense/transcript published"
        assert len(received) == 1
        msg = received[0]
        assert isinstance(msg, topics.Transcript)
        assert msg.text == "hello world"
        assert msg.is_final is True
        assert msg.language == "en"
        assert msg.node_id == "audio_session"
    finally:
        _stop_node(node, thread)


def test_multiple_phrases_publish_in_order(bus):
    """Two phrases fed serially come out in order (no reordering)."""
    adapter = _MockAdapter()
    received = []
    second = threading.Event()

    def on_transcript(msg):
        received.append(msg.text)
        if len(received) >= 2:
            second.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
    node, thread = _start_node(bus, adapter, poll_timeout_s=0.1)
    try:
        adapter.feed_phrase("first")
        adapter.feed_phrase("second")
        assert second.wait(timeout=3.0), f"only got {received}"
        assert received[:2] == ["first", "second"]
    finally:
        _stop_node(node, thread)


def test_empty_phrase_not_published(bus):
    """An empty/None phrase from the adapter shouldn't produce a
    Transcript message (saves the brain from receiving empty
    utterances)."""
    class _EmptyAdapter(_MockAdapter):
        def next_phrase(self, timeout=1.0):
            # Always return empty string — Whisper sometimes emits
            # these when the energy gate triggers on noise.
            time.sleep(min(0.1, timeout or 0.0))
            return ""
    adapter = _EmptyAdapter()
    received = []

    def on_transcript(msg):
        received.append(msg)

    bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
    node, thread = _start_node(bus, adapter, poll_timeout_s=0.1)
    try:
        time.sleep(0.3)  # let several ticks fire
        assert received == [], (
            f"empty phrases shouldn't publish; got {received}"
        )
    finally:
        _stop_node(node, thread)


def test_no_phrase_doesnt_publish(bus):
    """If next_phrase returns None (timeout), no message goes out."""
    adapter = _MockAdapter()  # never fed
    received = []

    def on_transcript(msg):
        received.append(msg)

    bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
    node, thread = _start_node(bus, adapter, poll_timeout_s=0.05)
    try:
        time.sleep(0.2)
        assert received == []
    finally:
        _stop_node(node, thread)


def test_user_speech_start_published_from_callback(bus):
    """The audio session's low-latency speech callback publishes a
    /sense/user_speech_start event before transcript finalization."""
    adapter = _MockAdapter()
    received = []
    event = threading.Event()

    def on_start(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_USER_SPEECH_START, on_start)
    node, thread = _start_node(bus, adapter, poll_timeout_s=0.1)
    try:
        adapter.fire_speech_start()
        assert event.wait(timeout=2.0), "no /sense/user_speech_start published"
        assert len(received) == 1
        msg = received[0]
        assert isinstance(msg, topics.UserSpeechStart)
        assert msg.node_id == "audio_session"
    finally:
        _stop_node(node, thread)


def test_sttnode_alias_still_available_for_one_release(bus):
    adapter = _MockAdapter()
    node = STTNode(bus=bus, adapter=adapter)
    assert isinstance(node, AudioSessionNode)


def test_transcript_publish_latency_smoke_bench(bus):
    """Smoke-quality realtime-path bench for Design Call 3.

    Measures local overhead from mock-STT phrase finalization to bus
    transcript delivery.  This is not a hardware STT latency benchmark.
    """
    adapter = _MockAdapter()
    event = threading.Event()
    elapsed = {"s": None}
    t0 = {"value": 0.0}

    def on_transcript(_msg):
        elapsed["s"] = time.perf_counter() - t0["value"]
        event.set()

    bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
    node, thread = _start_node(bus, adapter, poll_timeout_s=0.01)
    try:
        t0["value"] = time.perf_counter()
        adapter.feed_phrase("bench phrase")
        assert event.wait(timeout=2.0), "no transcript published"
        assert elapsed["s"] is not None
        print(
            "audio_session_transcript_publish_latency_ms="
            f"{elapsed['s'] * 1000:.3f}"
        )
        assert elapsed["s"] < 0.05
    finally:
        _stop_node(node, thread)
