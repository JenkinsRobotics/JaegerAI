"""Regression coverage for the Kokoro -> JaegerOS speaker boundary."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from jaeger_kokoro_tts.engine import KokoroTTS


class _RecordingPlayer:
    device_name = "bus:/act/speaker/pcm"
    amplitude = 0.0

    def __init__(self) -> None:
        self.enqueued: list[np.ndarray] = []
        self.ended = False
        self.correlation_id = None
        self.cancelled = False

    def begin(self, correlation_id=None) -> None:
        self.correlation_id = correlation_id

    def enqueue(self, audio) -> None:
        self.enqueued.append(np.asarray(audio, dtype=np.float32).copy())

    def mark_end(self) -> None:
        self.ended = True

    def wait_until_drained(self) -> bool:
        return True

    def cancel(self) -> None:
        self.cancelled = True


class _RecordingBus:
    def __init__(self) -> None:
        self.subscriptions = []

    def subscribe(self, topic, callback) -> None:
        self.subscriptions.append((topic, callback))

    def unsubscribe(self, topic, callback) -> None:
        self.subscriptions.remove((topic, callback))


def test_bus_speak_publishes_one_contiguous_utterance(monkeypatch):
    """Generator pauses must not look like separate utterance endings."""
    tts = KokoroTTS(bus=object())
    player = _RecordingPlayer()

    def pipeline(_text, *, voice, speed):
        assert voice == tts.voice
        assert speed == 1.25
        yield SimpleNamespace(audio=np.full(3, 0.25, dtype=np.float32))
        yield SimpleNamespace(audio=np.full(2, -0.5, dtype=np.float32))

    monkeypatch.setattr(tts, "_ensure_player", lambda: player)
    monkeypatch.setattr(tts, "_ensure_pipeline", lambda: pipeline)
    tts._player = player

    result = tts.speak(
        "hello cosmo", rate=1.25, correlation_id="utterance-9",
    )

    assert result["spoken"] is True
    assert result["samples"] == 5
    assert player.ended is True
    assert player.correlation_id == "utterance-9"
    assert len(player.enqueued) == 1
    assert np.array_equal(
        player.enqueued[0],
        np.array([0.25, 0.25, 0.25, -0.5, -0.5], dtype=np.float32),
    )


def test_bus_engine_never_resolves_a_local_hardware_backend(monkeypatch):
    bus = _RecordingBus()
    tts = KokoroTTS(bus=bus)

    def local_backend_is_a_bug():
        raise AssertionError("bus-backed TTS attempted local audio")

    monkeypatch.setattr(tts, "_resolve_backend", local_backend_is_a_bug)
    player = tts._ensure_player()
    try:
        assert player.backend == "bus"
        assert player.device_index is None
        assert player.device_name == "bus:/act/speaker/pcm"
    finally:
        tts.shutdown()


def test_stop_during_synthesis_does_not_publish_late_audio(monkeypatch):
    tts = KokoroTTS(bus=object())
    player = _RecordingPlayer()
    entered = threading.Event()
    release = threading.Event()
    result = {}

    def pipeline(_text, *, voice, speed):
        entered.set()
        release.wait(timeout=2.0)
        yield SimpleNamespace(audio=np.ones(240, dtype=np.float32))

    monkeypatch.setattr(tts, "_ensure_player", lambda: player)
    monkeypatch.setattr(tts, "_ensure_pipeline", lambda: pipeline)
    tts._player = player

    thread = threading.Thread(
        target=lambda: result.update(tts.speak("a long sentence")),
        daemon=True,
    )
    thread.start()
    assert entered.wait(timeout=2.0)
    tts.stop()
    release.set()
    thread.join(timeout=2.0)

    assert result["spoken"] is False
    assert result["reason"] == "interrupted"
    assert player.cancelled is True
    assert player.enqueued == []


@pytest.mark.parametrize("drain_result", [True, False])
def test_stop_during_drain_never_acknowledges_completed_playback(monkeypatch, drain_result):
    from jaeger_kokoro_tts.node import TTSNode
    from jaeger_os.contract import topics

    entered, release = threading.Event(), threading.Event()

    class Player(_RecordingPlayer):
        def wait_until_drained(self):
            entered.set()
            assert release.wait(2)
            return drain_result

        def cancel(self):
            super().cancel()
            release.set()

        def reset(self):
            raise AssertionError("cancellation was misclassified as a drain failure")

    class Bus:
        def __init__(self):
            self.messages = []

        def publish(self, message):
            self.messages.append(message)

    bus, player = Bus(), Player()
    engine = KokoroTTS(bus=bus)
    engine._player = player
    monkeypatch.setattr(engine, "_ensure_player", lambda: player)

    def pipeline(text, **kwargs):
        yield SimpleNamespace(audio=np.ones(4, dtype=np.float32))

    monkeypatch.setattr(engine, "_ensure_pipeline", lambda: pipeline)
    node = TTSNode(bus=bus, synthesizer=engine, warm_on_start=False,
                   install_signal_handlers=False)
    node._on_speech_command(topics.SpeechCommand(text="drain pending", correlation_id="drain-ui"))
    worker = threading.Thread(target=node.tick)
    worker.start()
    assert entered.wait(2)
    node._on_speech_stop(topics.SpeechStop(correlation_id="drain-ui"))
    worker.join(2)
    assert not worker.is_alive()
    assert player.cancelled is True
    assert len(player.enqueued) == 1  # PCM was queued before interruption.
    receipts = [m for m in bus.messages if isinstance(m, topics.SpokenAck)]
    assert len(receipts) == 1
    assert receipts[0].correlation_id == "drain-ui"
    assert receipts[0].ok is False
    assert receipts[0].reason == "interrupted"
