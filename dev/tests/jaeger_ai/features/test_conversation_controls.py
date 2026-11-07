import threading
from types import SimpleNamespace

from jaeger_ai.features.voice.control import next_mode
from jaeger_ai.features.voice.conversation import Conversation
from jaeger_ai.features.voice.vision import LocalVision


class Listener:
    def __init__(self):
        self.pauses = []

    def set_paused(self, value):
        self.pauses.append(value)


class Speaker:
    def __init__(self):
        self.spoken = []
        self.started = threading.Event()
        self.stopped = False

    def speak(self, text, *, cancel_event):
        if not cancel_event.is_set():
            self.spoken.append(text)
            self.started.set()
        return {"spoken": not cancel_event.is_set()}

    def stop(self):
        self.stopped = True


def test_modes_toggle_and_switch_without_enabling_camera_for_voice():
    assert next_mode("off", "voice") == "voice"
    assert next_mode("voice", "voice") == "off"
    assert next_mode("voice", "video") == "video"
    assert next_mode("video", "off") == "off"


def test_speech_begins_before_gateway_finishes_and_reasoning_is_not_spoken():
    speaker = Speaker()

    class Gateway:
        def stream_turn(self, *args, on_event, **kwargs):
            on_event("turn.reasoning", {"delta": "private reasoning"})
            on_event("turn.delta", {"delta": "Hello. "})
            assert speaker.started.wait(2)
            on_event("turn.delta", {"delta": "How are you?"})
            return SimpleNamespace(ok=True, text="Hello. How are you?")

    listener = Listener()
    Conversation(listener, speaker, gateway=Gateway()).turn("hello")
    assert speaker.spoken == ["Hello.", "How are you?"]
    assert listener.pauses == [True, False, True, False]


def test_completed_reply_without_deltas_is_spoken_once():
    gateway = SimpleNamespace(stream_turn=lambda *args, **kwargs: SimpleNamespace(ok=True, text="Hello"))
    speaker = Speaker()
    Conversation(Listener(), speaker, gateway=gateway).turn("hello")
    assert speaker.spoken == ["Hello"]


def test_camera_context_only_in_execution_not_display_text():
    received = {}

    def turn(session, text, **kwargs):
        received.update(text=text, **kwargs)
        return SimpleNamespace(ok=True, text="A mug")

    vision = SimpleNamespace(latest=lambda: "2 seconds ago: a blue mug")
    Conversation(Listener(), Speaker(), gateway=SimpleNamespace(stream_turn=turn), vision=vision).turn("What is this?")
    assert received["display_text"] == "What is this?"
    assert "blue mug" in received["text"]
    assert received["fast_lane"] is True


def test_stale_camera_observations_are_withheld():
    vision = LocalVision(0, "unused", lambda **fields: None)
    vision.observation = "old image"
    assert vision.latest() == ""


def test_interruption_cancels_request_and_prevents_later_speech():
    cancelled = threading.Event()
    speaker = Speaker()

    class Gateway:
        def cancel(self, *args):
            cancelled.set()

        def stream_turn(self, *args, on_event, **kwargs):
            session.interrupt()
            on_event("turn.delta", {"delta": "Should not speak."})
            return SimpleNamespace(ok=True, text="Should not speak.")

    session = Conversation(Listener(), speaker, gateway=Gateway(), duplex=True)
    session.turn("hello")
    assert cancelled.wait(2)
    assert speaker.stopped and not speaker.spoken
