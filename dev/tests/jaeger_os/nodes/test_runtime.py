"""Tests for ``jaeger_os.nodes.runtime`` — Track B.2.1.

Runtime is the brain-side singleton that creates the bus and starts
the co-located TTS node.  These tests use injected factories so they
exercise the real runtime/thread path without loading Kokoro or
touching audio hardware.
"""

from __future__ import annotations

import uuid
import queue

from jaeger_os.transport import topics
from jaeger_os.core.audio import AudioSessionConfig
from jaeger_os.nodes import runtime
from jaeger_os.nodes.tts import TTSNode
from jaeger_os.transport import InProcBus


class _MockSynth:
    def __init__(self, *, warm_raises: bool = False):
        self.calls: list[str] = []
        self.warm_calls = 0
        self.shutdown_called = False
        self.warm_raises = warm_raises
        self.reference_buffer = None

    def speak(self, text: str):
        self.calls.append(text)
        return {"spoken": True, "elapsed_s": 0.01}

    def warm(self):
        self.warm_calls += 1
        if self.warm_raises:
            raise RuntimeError("warm failed")
        return {"warmed": True}

    def shutdown(self):
        self.shutdown_called = True


def _install_mock_runtime(monkeypatch, *, synth: _MockSynth | None = None):
    runtime.shutdown()
    synth = synth or _MockSynth()
    created: dict[str, object] = {"synth": synth}

    def synth_factory():
        return synth

    def node_factory(*, bus, synthesizer):
        node = TTSNode(
            bus=bus,
            synthesizer=synthesizer,
            name="tts",
            install_signal_handlers=False,
        )
        created["node"] = node
        return node

    monkeypatch.setattr(runtime, "_bus_factory", InProcBus)
    monkeypatch.setattr(runtime, "_synth_factory", synth_factory)
    monkeypatch.setattr(runtime, "_tts_node_factory", node_factory)
    return created


class _MockAudioSession:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.on_speech_detected = None
        self.phrases: "queue.Queue[str]" = queue.Queue()
        self.reference_buffer = None
        self.barge_in_live = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def next_phrase(self, timeout=1.0):
        try:
            return self.phrases.get(timeout=timeout)
        except queue.Empty:
            return None

    def set_on_speech_detected(self, callback):
        self.on_speech_detected = callback

    def feed(self, text):
        self.phrases.put(text)


def test_get_bus_returns_same_instance():
    """Repeated calls return the SAME Bus — it's a singleton."""
    runtime.shutdown()
    try:
        a = runtime.get_bus()
        b = runtime.get_bus()
        assert a is b
    finally:
        runtime.shutdown()


def test_get_bus_creates_inproc_bus():
    runtime.shutdown()
    try:
        bus = runtime.get_bus()
        assert isinstance(bus, InProcBus)
    finally:
        runtime.shutdown()


def test_shutdown_clears_bus_singleton():
    runtime.shutdown()
    bus1 = runtime.get_bus()
    runtime.shutdown()
    assert bus1 is not None
    assert runtime._bus is None


def test_shutdown_is_idempotent():
    runtime.shutdown()
    runtime.shutdown()
    runtime.shutdown()  # no raise


def test_shutdown_then_get_bus_creates_fresh_bus():
    """After shutdown, a subsequent get_bus() gets a NEW bus, not
    the closed one."""
    runtime.shutdown()
    bus1 = runtime.get_bus()
    runtime.shutdown()
    bus2 = runtime.get_bus()
    try:
        assert bus1 is not bus2
    finally:
        runtime.shutdown()


def test_ensure_tts_node_starts_node_and_installs_subscriber(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    try:
        node = runtime.ensure_tts_node()
        bus = runtime.get_bus()

        cid = uuid.uuid4().hex
        ack = bus.request(
            topics.SpeechCommand(text="ready", correlation_id=cid),
            ack_topic=topics.SENSE_SPOKEN,
            timeout_s=1.0,
        )

        assert node is created["node"]
        assert ack is not None
        assert ack.ok is True
        assert ack.correlation_id == cid
        assert created["synth"].calls == ["ready"]
    finally:
        runtime.shutdown()


def test_ensure_tts_node_warm_failure_is_nonfatal(monkeypatch, capsys):
    synth = _MockSynth(warm_raises=True)
    _install_mock_runtime(monkeypatch, synth=synth)
    try:
        node = runtime.ensure_tts_node(warm=True)
        assert node is runtime._tts_node
        assert synth.warm_calls == 1
        assert "warm at ensure_tts_node failed" in capsys.readouterr().err
    finally:
        runtime.shutdown()


def test_shutdown_stops_node_thread_and_synth(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    runtime.ensure_tts_node()
    synth = created["synth"]

    runtime.shutdown()

    assert runtime._tts_node is None
    assert runtime._tts_thread is None
    assert runtime._bus is None
    assert synth.shutdown_called is True


def test_ensure_audio_session_node_publishes_transcript(monkeypatch):
    created = _install_mock_runtime(monkeypatch)
    session = _MockAudioSession()
    monkeypatch.setattr(
        runtime,
        "_audio_session_factory",
        lambda _config: session,
    )
    try:
        node = runtime.ensure_audio_session_node(
            config=AudioSessionConfig(require_wake_word=False),
        )
        bus = runtime.get_bus()
        got = []

        def on_transcript(msg):
            got.append(msg)

        bus.subscribe(topics.SENSE_TRANSCRIPT, on_transcript)
        session.feed("hello via audio node")
        import time
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not got:
            time.sleep(0.01)

        assert node is runtime._audio_session_node
        assert session.started is True
        assert got
        assert got[0].text == "hello via audio node"
        assert got[0].node_id == "audio_session"
        assert created["synth"] is runtime.get_synth()
    finally:
        runtime.shutdown()


def test_shutdown_audio_session_node_leaves_tts_running(monkeypatch):
    _install_mock_runtime(monkeypatch)
    session = _MockAudioSession()
    monkeypatch.setattr(
        runtime,
        "_audio_session_factory",
        lambda _config: session,
    )
    try:
        runtime.ensure_audio_session_node(
            config=AudioSessionConfig(require_wake_word=False),
        )
        assert runtime._tts_node is not None

        runtime.shutdown_audio_session_node()

        assert session.stopped is True
        assert runtime._audio_session_node is None
        assert runtime._audio_session_thread is None
        assert runtime._tts_node is not None
    finally:
        runtime.shutdown()
