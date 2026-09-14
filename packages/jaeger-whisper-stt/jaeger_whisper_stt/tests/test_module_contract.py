"""Module-contract smoke for ``jaeger_whisper_stt`` — 0.8 M2b.

Not part of ``dev/tests`` (``pyproject.toml``'s ``testpaths`` doesn't
include this package — same pattern as
``jaeger_os/nodes/kokoro_tts/tests/test_module_contract.py``). Run
directly:

    pytest jaeger_os/jaeger_whisper_stt/tests
    python -m jaeger_whisper_stt.tests.test_module_contract

Three things a module must get right, proven here without touching
microphone hardware or loading the Whisper model weights:

  1. ``module.yaml`` parses and carries the fields the (future) module
     loader will require.
  2. ``AudioSessionNode`` builds correctly-wired on an injected bus —
     via direct construction with a fake :class:`STTAdapter`, NOT the
     manifest's ``make_audio_session_node`` factory. Unlike kokoro_tts's
     ``KokoroTTS`` (lazy — no model load until ``warm()``/``speak()``),
     whisper_stt's real engine (``WhisperSTTTwoPass``/``WhisperSTTContinuous``)
     loads live pywhispercpp models synchronously in its ``__init__``, so
     driving the smoke through the real factory would pull in heavy
     model weights + the ``pywhispercpp`` dependency. The fake adapter
     keeps this test hermetic.
  3. The node's actual bus contract (adapter phrase -> transcript out)
     works, via the fake adapter so no real engine is invoked.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import threading
import time

import yaml

from jaeger_whisper_stt import AudioSessionNode
from jaeger_os.nodes.base import NodeState
from jaeger_os.transport import InProcBus, topics

_MODULE_DIR = pathlib.Path(__file__).resolve().parent.parent


class _FakeAdapter:
    """Drop-in for the :class:`STTAdapter` Protocol — no mic, no model."""

    def __init__(self) -> None:
        self._phrases: list[str] = []
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        deadline = time.monotonic() + (timeout or 0.0)
        while time.monotonic() < deadline:
            if self._phrases:
                return self._phrases.pop(0)
            time.sleep(0.01)
        return None

    def set_paused(self, paused: bool) -> None:
        pass

    def set_on_speech_detected(self, callback) -> None:
        pass

    def open_followup(self) -> None:
        pass

    def drain_pending(self) -> None:
        pass

    def health(self) -> dict:
        return {
            "started": self.started,
            "running": self.started and not self.stopped,
            "decode_failures": 0,
            "output_drops": 0,
            "mic": {},
        }

    def feed_phrase(self, text: str) -> None:
        self._phrases.append(text)


def test_module_yaml_validates() -> None:
    doc = yaml.safe_load((_MODULE_DIR / "module.yaml").read_text())
    assert doc["module"] == "whisper_stt"
    assert doc["slot"] == "stt"
    # 2.0.0: the topic rename is a breaking contract change, and
    # module.yaml's own rule calls for a MAJOR bump on one. Anything
    # pinning 1.x targets the flat namespace and will not find these
    # topics.
    assert doc["version"] == "2.0.0"
    # Was [] until the audio driver existed — which was a lie by
    # omission: this module consumed audio constantly, just not from a
    # topic, so the manifest could not see it.
    assert doc["consumes"] == ["/sense/mic/pcm"]
    assert doc["produces"] == [
        "/sense/stt/transcript", "/sense/stt/speech_start",
        "/sys/gate/decision",
    ]
    assert doc["tools"] == ["listen"]
    assert doc["factory"] == "jaeger_whisper_stt:make_audio_session_node"
    assert doc["config"] == "whisper_stt"
    assert doc["requires_libraries"] == [
        "pywhispercpp", "webrtcvad", "numpy",
    ]


def test_factory_import_does_not_import_optional_engine_methods() -> None:
    """App discovery needs the factory, not every experimental algorithm.

    A broken caption-mode export must not prevent a proven two-pass app from
    reaching the point where its configured method is selected.
    """
    code = """
import sys
from jaeger_whisper_stt import make_audio_session_node
optional = ('.engine.window', '.engine.phrase_word', '.engine.local_agreement')
assert not any(any(part in name for part in optional) for name in sys.modules)
assert callable(make_audio_session_node)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], text=True, capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_node_builds_on_an_inproc_bus_with_a_fake_adapter() -> None:
    """Direct ``AudioSessionNode`` construction — no model load, no
    audio device, no network. See module docstring for why this
    bypasses ``make_audio_session_node``."""
    bus = InProcBus()
    node = AudioSessionNode(
        bus=bus, adapter=_FakeAdapter(), install_signal_handlers=False,
    )
    try:
        assert isinstance(node, AudioSessionNode)
        assert node.bus is bus
        assert node.session is not None
    finally:
        bus.close()


def test_transcript_round_trip_with_a_fake_adapter() -> None:
    """The node's bus contract, independent of ``make_audio_session_node``'s
    real engine: an adapter-committed phrase becomes a
    ``/sense/stt/transcript`` publish."""
    bus = InProcBus()
    adapter = _FakeAdapter()
    node = AudioSessionNode(
        bus=bus, adapter=adapter, poll_timeout_s=0.1,
        install_signal_handlers=False,
    )
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and node.state != NodeState.RUNNING:
            time.sleep(0.01)
        assert node.state == NodeState.RUNNING

        received: list[topics.Transcript] = []
        event = threading.Event()

        def _on_transcript(msg: topics.TopicMessage) -> None:
            received.append(msg)
            event.set()

        bus.subscribe(topics.SENSE_STT_TRANSCRIPT, _on_transcript)
        adapter.feed_phrase("module contract smoke")
        assert event.wait(timeout=2.0), "no /sense/stt/transcript published"
        assert received[0].text == "module contract smoke"
        health = node.health()
        assert health["final_transcripts"] == 1
        assert health["engine"]["running"] is True
    finally:
        node.stop()
        thread.join(timeout=2.0)
        bus.close()


if __name__ == "__main__":
    test_module_yaml_validates()
    test_node_builds_on_an_inproc_bus_with_a_fake_adapter()
    test_transcript_round_trip_with_a_fake_adapter()
    print("whisper_stt module contract smoke: OK")
