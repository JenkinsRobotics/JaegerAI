"""Module-contract smoke for ``jaeger_os.nodes.kokoro_tts`` — 0.8 M1.

Not part of ``dev/tests`` (``pyproject.toml``'s ``testpaths`` doesn't
include this package — same pattern as the old ``jaeger_os/plugins/
kokoro_tts/tests/smoke_test.py`` it replaces). Run directly:

    pytest jaeger_os/nodes/kokoro_tts/tests
    python -m jaeger_os.nodes.kokoro_tts.tests.test_module_contract

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

from jaeger_os.nodes.kokoro_tts import TTSNode, make_tts_node
from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus, topics

_MODULE_DIR = pathlib.Path(__file__).resolve().parent.parent


def test_module_yaml_validates() -> None:
    doc = yaml.safe_load((_MODULE_DIR / "module.yaml").read_text())
    assert doc["module"] == "kokoro_tts"
    assert doc["slot"] == "tts"
    assert doc["version"] == "1.0.0"
    assert doc["consumes"] == ["/act/speech", "/act/speech_stop"]
    assert doc["produces"] == ["/sense/spoken", "/sense/tts_chunk"]
    assert doc["tools"] == ["text_to_speech"]
    assert doc["factory"] == "jaeger_os.nodes.kokoro_tts:make_tts_node"
    assert doc["config"] == "kokoro_tts"


def test_factory_builds_a_live_node_on_an_inproc_bus() -> None:
    """``make_tts_node`` (the ``module.yaml``'s ``factory:`` entrypoint)
    constructs a real ``TTSNode`` wired to a real (but not yet
    warmed/loaded) ``KokoroTTS`` — no model load, no audio device, no
    network. Doesn't call ``.speak()`` (that would need hardware)."""
    bus = InProcBus()
    node = make_tts_node(bus, {})
    try:
        assert isinstance(node, TTSNode)
        assert node.bus is bus
        # KokoroTTS is lazy — constructing it must not have touched the
        # kokoro library or opened an audio device.
        assert node.synthesizer is not None
        assert getattr(node.synthesizer, "_pipeline", "unset") is None
    finally:
        node.synthesizer.shutdown()
        bus.close()


def test_speak_round_trip_with_a_fake_synth() -> None:
    """The node's bus contract, independent of ``make_tts_node``'s real
    engine: publish a SpeechCommand, get a SpokenAck back."""

    class _FakeSynth:
        def speak(self, text: str) -> dict:
            return {"spoken": True, "elapsed_s": 0.01}

        def shutdown(self) -> None:
            pass

    bus = InProcBus()
    node = TTSNode(bus=bus, synthesizer=_FakeSynth(),
                   install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node.state != NodeState.RUNNING:
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING

        ack = bus.request(
            topics.SpeechCommand(text="module contract smoke"),
            ack_topic=topics.SENSE_SPOKEN,
            timeout_s=2.0,
        )
        assert ack is not None
        assert ack.ok is True
    finally:
        node.stop()
        thread.join(timeout=2.0)
        bus.close()


if __name__ == "__main__":
    test_module_yaml_validates()
    test_factory_builds_a_live_node_on_an_inproc_bus()
    test_speak_round_trip_with_a_fake_synth()
    print("kokoro_tts module contract smoke: OK")
