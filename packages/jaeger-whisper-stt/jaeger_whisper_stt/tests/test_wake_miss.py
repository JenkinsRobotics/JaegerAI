"""Heard-but-not-addressed has to reach the bus.

A wake-gated engine that drops a phrase silently is indistinguishable
from a dead microphone: both produce no message. This is the path that
tells them apart, so it gets a test rather than a comment.
"""

from __future__ import annotations

from jaeger_os.transport import InProcBus, topics

from jaeger_whisper_stt.engine._base import WakeMissNotifier
from jaeger_whisper_stt.node import AudioSessionNode


class _Adapter(WakeMissNotifier):
    """Minimal stand-in for a wake-gated pipeline."""

    def start(self): pass
    def stop(self): pass
    def next_phrase(self, timeout=0.0): return None


class _Session:
    """AudioSession stand-in that forwards nothing — the node must fall
    back to probing the adapter, which is the real wiring path."""

    def __init__(self, adapter):
        self.adapter = adapter

    # Present because the real AudioSession has it and node.setup()
    # calls it unguarded. Deliberately NOT defining set_on_wake_miss or
    # set_on_partial: that is what forces the node down the adapter
    # fallback, which is the path under test.
    def set_on_speech_detected(self, callback): pass

    def start(self): pass
    def stop(self): pass
    def next_phrase(self, timeout=0.0): return None


def _node_with_adapter():
    bus = InProcBus()
    adapter = _Adapter()
    node = AudioSessionNode(bus=bus, session=_Session(adapter), name="stt",
                            install_signal_handlers=False)
    seen = []
    bus.subscribe(topics.SYS_GATE_DECISION, seen.append)
    node.setup()
    return bus, adapter, seen


def test_a_phrase_without_the_wake_word_becomes_a_gate_decision():
    bus, adapter, seen = _node_with_adapter()
    try:
        adapter._notify_wake_miss("what time is it")
        bus.drain() if hasattr(bus, "drain") else None
        import time; time.sleep(0.2)
        assert len(seen) == 1, f"expected one GateDecision, got {seen}"
        msg = seen[0]
        assert msg.accepted is False
        assert msg.reason == "no_wake"
        assert msg.text == "what time is it"
    finally:
        bus.close()


def test_the_notifier_survives_a_throwing_listener():
    """It runs on the decode thread. A broken voice-activity log must
    never cost you the microphone."""
    adapter = _Adapter()
    adapter.set_on_wake_miss(lambda text: 1 / 0)
    adapter._notify_wake_miss("boom")   # must not raise


def test_no_listener_is_not_an_error():
    """Rolling methods have no engine-side wake stage and never wire
    this; the absence has to be silent, not a crash."""
    _Adapter()._notify_wake_miss("nobody listening")


def test_text_is_bounded():
    """It rides a bus message; an unbounded transcript would put an
    arbitrarily large payload on a telemetry topic."""
    bus, adapter, seen = _node_with_adapter()
    try:
        adapter._notify_wake_miss("x" * 5000)
        import time; time.sleep(0.2)
        assert len(seen) == 1
        assert len(seen[0].text) <= 200
    finally:
        bus.close()
