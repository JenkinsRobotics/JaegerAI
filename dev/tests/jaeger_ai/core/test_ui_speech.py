from __future__ import annotations

import threading

from jaeger_os.contract import topics
from jaeger_os.nodes import runtime

from jaeger_ai.core.ui_speech import UISpeech


class _Bus:
    def __init__(self) -> None:
        self.commands = []
        self.published = []
        self.callbacks = []
        self.changed = threading.Condition()
        self.fail_stop = False

    def subscribe(self, topic, callback):
        assert topic == topics.ACT_SPEECH_SPOKEN
        self.callbacks.append(callback)

    def unsubscribe(self, topic, callback):
        self.callbacks.remove(callback)

    def publish(self, message):
        if isinstance(message, topics.SpeechStop) and self.fail_stop:
            raise RuntimeError("transport closed")
        with self.changed:
            self.published.append(message)
            if isinstance(message, topics.SpeechCommand):
                self.commands.append(message)
            self.changed.notify_all()

    def wait_commands(self, count):
        with self.changed:
            assert self.changed.wait_for(lambda: len(self.commands) >= count, 2)

    def ack(self, command, *, ok=True):
        ack = topics.SpokenAck(ok=ok, duration_s=0.25,
                               correlation_id=command.correlation_id)
        for callback in list(self.callbacks):
            callback(ack)


def _setup(monkeypatch):
    bus = _Bus()
    monkeypatch.setattr(runtime, "ensure_tts_node", lambda: object())
    monkeypatch.setattr(runtime, "get_bus", lambda: bus)
    return bus, UISpeech(timeout_s=2)


def _speak(speech, text, result):
    worker = threading.Thread(target=lambda: result.update(
        speech.speak(text, voice="am_adam", rate=0.95)))
    worker.start()
    return worker


def test_ui_speech_uses_framework_voice_rate_and_matching_ack(monkeypatch):
    bus, speech = _setup(monkeypatch)
    result = {}
    worker = _speak(speech, "System online.", result)
    bus.wait_commands(1)
    command = bus.commands[0]
    assert command.voice == "am_adam"
    assert command.rate == 0.95
    assert command.node_id == "jaeger-ai-interface"
    # An unrelated producer's acknowledgement must not settle this lane.
    bus.ack(topics.SpeechCommand(text="other", correlation_id="unrelated"))
    assert worker.is_alive()
    bus.ack(command)
    worker.join(2)
    assert not worker.is_alive()
    assert result["spoken"] is True
    assert result["acknowledged"] is True
    assert not bus.callbacks


def test_stop_discards_pending_lane_and_preserves_active_identity(monkeypatch):
    bus, speech = _setup(monkeypatch)
    first, queued, new = {}, {}, {}
    active = _speak(speech, "first", first)
    bus.wait_commands(1)
    waiting = _speak(speech, "discard me", queued)
    with speech._lock:
        assert speech._lock.wait_for(lambda: len(speech._pending) == 1, 2)
    stopped = speech.stop()
    waiting.join(2)
    assert not waiting.is_alive()
    assert queued["cancelled"] is True
    assert len(bus.commands) == 1
    assert stopped["stopped"] is False  # publication is not an audio receipt
    assert stopped["stop_requested"] is True
    assert stopped["discarded"] == 1
    assert bus.published[-1].correlation_id == bus.commands[0].correlation_id
    followup = _speak(speech, "new", new)
    assert speech.active_correlation_id == bus.commands[0].correlation_id
    bus.ack(bus.commands[0])  # late successful ack cannot revive cancelled work
    active.join(2)
    bus.wait_commands(2)
    assert first["spoken"] is False
    assert first["acknowledged"] is True
    assert [c.text for c in bus.commands] == ["first", "new"]
    bus.ack(bus.commands[1])
    followup.join(2)
    assert new["spoken"] is True
    assert not bus.callbacks


def test_idle_stop_never_publishes_global_stop(monkeypatch):
    bus, speech = _setup(monkeypatch)
    assert speech.stop() == {"stopped": True, "active": False, "discarded": 0}
    assert bus.published == []


def test_stop_publication_failure_is_visible(monkeypatch):
    bus, speech = _setup(monkeypatch)
    result = {}
    worker = _speak(speech, "first", result)
    bus.wait_commands(1)
    bus.fail_stop = True
    stopped = speech.stop()
    assert stopped["stopped"] is False
    assert stopped["stop_requested"] is False
    assert stopped["error"] == "transport closed"
    bus.ack(bus.commands[0])
    worker.join(2)
    assert result["spoken"] is False


def test_timeout_reports_unknown_and_releases_subscription(monkeypatch):
    bus, speech = _setup(monkeypatch)
    speech.timeout_s = 0.01
    result = speech.speak("hello", voice="am_adam")
    assert result["execution_unknown"] is True
    assert result["acknowledged"] is False
    assert not bus.callbacks
    assert speech.active_correlation_id is None


def test_stop_during_prepare_prevents_later_publication(monkeypatch):
    bus, speech = _setup(monkeypatch)
    preparing, release = threading.Event(), threading.Event()

    def prepare():
        preparing.set()
        assert release.wait(2)

    monkeypatch.setattr(runtime, "ensure_tts_node", prepare)
    result = {}
    worker = _speak(speech, "old", result)
    assert preparing.wait(2)
    speech.stop()
    release.set()
    worker.join(2)
    assert result["cancelled"] is True
    assert bus.published == []


def test_ui_speech_rejects_invalid_input_without_starting_runtime(monkeypatch):
    monkeypatch.setattr(runtime, "ensure_tts_node", lambda: (_ for _ in ()).throw(
        AssertionError("runtime started")))
    speech = UISpeech()
    assert speech.speak("  ")["spoken"] is False
    assert speech.speak("hello", rate=3.0)["spoken"] is False
    assert speech.stop()["active"] is False


def test_stop_does_not_cancel_another_lane_on_shared_bus(monkeypatch):
    bus, first_lane = _setup(monkeypatch)
    other_lane = UISpeech(timeout_s=2)
    first, other = {}, {}
    first_worker = _speak(first_lane, "interface one", first)
    bus.wait_commands(1)
    other_worker = _speak(other_lane, "unrelated producer", other)
    bus.wait_commands(2)
    first_lane.stop()
    stops = [message for message in bus.published if isinstance(message, topics.SpeechStop)]
    assert len(stops) == 1
    assert stops[0].correlation_id == bus.commands[0].correlation_id
    assert stops[0].correlation_id != bus.commands[1].correlation_id
    bus.ack(bus.commands[1])
    other_worker.join(2)
    assert other["spoken"] is True
    bus.ack(bus.commands[0], ok=False)
    first_worker.join(2)
    assert first["cancelled"] is True
    assert not bus.callbacks
