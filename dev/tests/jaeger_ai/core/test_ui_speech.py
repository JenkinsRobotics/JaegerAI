from __future__ import annotations

import threading

from jaeger_os.contract import topics
from jaeger_os.nodes import runtime

from jaeger_ai.core.ui_speech import UISpeech


class _Bus:
    def __init__(self) -> None:
        self.command = None
        self.published = []
        self.started = threading.Event()
        self.release = threading.Event()

    def request(self, command, *, ack_topic, timeout_s):
        self.command = command
        self.ack_topic = ack_topic
        self.timeout_s = timeout_s
        self.started.set()
        self.release.wait(2)
        return topics.SpokenAck(
            ok=True, duration_s=0.25,
            correlation_id=command.correlation_id,
        )

    def publish(self, message):
        self.published.append(message)
        self.release.set()


def test_ui_speech_uses_framework_voice_rate_and_matching_stop(monkeypatch):
    bus = _Bus()
    monkeypatch.setattr(runtime, "ensure_tts_node", lambda: object())
    monkeypatch.setattr(runtime, "get_bus", lambda: bus)
    speech = UISpeech(timeout_s=7)
    result = {}

    worker = threading.Thread(
        target=lambda: result.update(speech.speak(
            "System online.", voice="am_adam", rate=0.95)))
    worker.start()
    assert bus.started.wait(2)

    stopped = speech.stop()
    worker.join(2)

    assert isinstance(bus.command, topics.SpeechCommand)
    assert bus.command.voice == "am_adam"
    assert bus.command.rate == 0.95
    assert bus.command.node_id == "jaeger-ai-interface"
    assert bus.ack_topic == topics.ACT_SPEECH_SPOKEN
    assert bus.timeout_s == 7
    assert result["spoken"] is True
    assert stopped["active"] is True
    assert isinstance(bus.published[0], topics.SpeechStop)
    assert bus.published[0].correlation_id == bus.command.correlation_id


def test_ui_speech_rejects_invalid_input_without_starting_runtime(monkeypatch):
    monkeypatch.setattr(
        runtime, "ensure_tts_node",
        lambda: (_ for _ in ()).throw(AssertionError("runtime started")),
    )
    speech = UISpeech()
    assert speech.speak("  ")["spoken"] is False
    assert speech.speak("hello", rate=3.0)["spoken"] is False
    assert speech.stop() == {"stopped": True, "active": False}
