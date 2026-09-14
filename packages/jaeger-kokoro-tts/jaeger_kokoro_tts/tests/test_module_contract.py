"""Module-contract smoke for ``jaeger_kokoro_tts`` — 0.8 M1.

Not part of ``dev/tests`` (``pyproject.toml``'s ``testpaths`` doesn't
include this package — same pattern as the old ``jaeger_os/plugins/
kokoro_tts/tests/smoke_test.py`` it replaces). Run directly:

    pytest jaeger_os/jaeger_kokoro_tts/tests
    python -m jaeger_kokoro_tts.tests.test_module_contract

Three things a module must get right, proven here without touching
audio hardware or the Kokoro model weights:

  1. ``module.yaml`` parses and carries the fields the (future) module
     loader will require.
  2. The chassis-contract factory (``make_tts_node``) builds a live,
     correctly-wired node on an injected bus.
  3. The node's actual bus contract (speech in -> ack out) works, via
     a fake ``Synthesizer`` so no real engine is invoked.
"""

from __future__ import annotations

import pathlib
import threading
import time

import yaml

from jaeger_kokoro_tts import TTSNode, make_tts_node
from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus, topics

_MODULE_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_module_yaml_validates() -> None:
    doc = yaml.safe_load((_MODULE_DIR / "module.yaml").read_text())
    assert doc["module"] == "kokoro_tts"
    assert doc["slot"] == "tts"
    # 2.0.0: the topic rename is a breaking contract change, and
    # module.yaml's own rule calls for a MAJOR bump on one. Anything
    # pinning 1.x targets the flat namespace and will not find these
    # topics.
    assert doc["version"] == "2.0.0"
    # /act/speaker/* joined the surface when this module stopped
    # opening the output device: it publishes audio for the audio_io
    # driver to play, and listens for the driver's drain signal because
    # a publisher cannot tell "finished sending" from "finished
    # playing" on its own.
    assert doc["consumes"] == ["/act/speech/say", "/act/speech/stop",
                               "/act/speaker/state"]
    assert doc["produces"] == ["/act/speech/spoken", "/act/speech/chunk",
                               "/act/speaker/pcm", "/act/speaker/stop"]
    assert doc["tools"] == ["text_to_speech"]
    assert doc["factory"] == "jaeger_kokoro_tts:make_tts_node"
    assert doc["config"] == "kokoro_tts"


def test_factory_builds_a_live_node_on_an_inproc_bus() -> None:
    """``make_tts_node`` (the ``module.yaml``'s ``factory:`` entrypoint)
    constructs a real ``TTSNode`` wired to a real (but not yet
    warmed/loaded) ``KokoroTTS`` — no model load, no audio device, no
    network. Doesn't call ``.speak()`` (that would need hardware)."""
    bus = InProcBus()
    node = make_tts_node(bus, {
        "voice": "bm_george",
        "lang": "b",
        "warm": False,
        "queue_maxsize": 7,
        "max_text_chars": 321,
    })
    try:
        assert isinstance(node, TTSNode)
        assert node.bus is bus
        # KokoroTTS is lazy — constructing it must not have touched the
        # kokoro library or opened an audio device.
        assert node.synthesizer is not None
        assert getattr(node.synthesizer, "_pipeline", "unset") is None
        assert node.synthesizer.bus is bus
        assert node.synthesizer._PlayerCls.__name__ == "BusPlayer"
        assert node.synthesizer.voice == "bm_george"
        assert node.synthesizer.lang == "b"
        assert node.health()["queue_capacity"] == 7
        assert node._max_text_chars == 321
    finally:
        node.synthesizer.shutdown()
        bus.close()


def test_speak_round_trip_with_a_fake_synth() -> None:
    """The node's bus contract, independent of ``make_tts_node``'s real
    engine: publish a SpeechCommand, get a SpokenAck back."""

    class _FakeSynth:
        def __init__(self):
            self.calls = []

        def speak(self, text: str, **kwargs) -> dict:
            self.calls.append((text, kwargs))
            return {"spoken": True, "elapsed_s": 0.01}

        def shutdown(self) -> None:
            pass

    bus = InProcBus()
    synth = _FakeSynth()
    node = TTSNode(bus=bus, synthesizer=synth,
                   warm_on_start=False,
                   install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node.state != NodeState.RUNNING:
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING

        ack = bus.request(
            topics.SpeechCommand(
                text="module contract smoke",
                voice="bm_george",
                rate=1.2,
            ),
            ack_topic=topics.ACT_SPEECH_SPOKEN,
            timeout_s=2.0,
        )
        assert ack is not None
        assert ack.ok is True
        assert synth.calls[0][1]["voice"] == "bm_george"
        assert synth.calls[0][1]["rate"] == 1.2
        assert synth.calls[0][1]["correlation_id"] == ack.correlation_id
        health = node.health()
        assert health["requests"] == 1
        assert health["completed"] == 1
    finally:
        node.stop()
        thread.join(timeout=2.0)
        bus.close()


def test_invalid_requests_fail_immediately_without_loading_kokoro() -> None:
    class _NeverCalled:
        def speak(self, text: str) -> dict:
            raise AssertionError("invalid request reached the synthesizer")

        def shutdown(self) -> None:
            pass

    bus = InProcBus()
    node = TTSNode(
        bus=bus,
        synthesizer=_NeverCalled(),
        max_text_chars=5,
        warm_on_start=False,
    )
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node.state != NodeState.RUNNING:
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING
        for request in (
            topics.SpeechCommand(text="   "),
            topics.SpeechCommand(text="too long"),
            topics.SpeechCommand(text="hello", rate=4.0),
        ):
            ack = bus.request(
                request,
                ack_topic=topics.ACT_SPEECH_SPOKEN,
                timeout_s=1.0,
            )
            assert ack is not None and ack.ok is False
        assert node.health()["rejected"] == 3
    finally:
        node.stop()
        thread.join(timeout=2.0)
        bus.close()


if __name__ == "__main__":
    test_module_yaml_validates()
    test_factory_builds_a_live_node_on_an_inproc_bus()
    test_speak_round_trip_with_a_fake_synth()
    print("kokoro_tts module contract smoke: OK")
