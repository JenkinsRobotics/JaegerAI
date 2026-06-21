"""Tests for ``jaeger_os.nodes.software.tts`` — Track B.1.

Mock synthesizer so we exercise the Bus + node + ack contract without
touching audio hardware or model loading.  Real-Kokoro integration
runs out-of-band via ``./launch --tts-test`` (Track B.1.4).
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import pytest

from jaeger_os import topics
from jaeger_os.nodes import TTSNode
from jaeger_os.transport import InProcBus


# ── mock synthesizer ──────────────────────────────────────────────

class _MockSynth:
    """Records calls; returns canned results.  Drop-in for the
    Synthesizer Protocol the TTS node depends on."""

    def __init__(
        self,
        *,
        result: dict | None = None,
        delay_s: float = 0.0,
        raise_on_speak: Exception | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.shutdown_called = False
        self._result = result or {"spoken": True, "elapsed_s": 0.01}
        self._delay_s = delay_s
        self._raise = raise_on_speak

    def speak(self, text: str) -> dict[str, Any]:
        self.calls.append(text)
        if self._delay_s:
            time.sleep(self._delay_s)
        if self._raise is not None:
            raise self._raise
        return dict(self._result)

    def shutdown(self) -> None:
        self.shutdown_called = True


# ── fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _start_node(bus, synth, **kwargs) -> tuple[TTSNode, threading.Thread]:
    node = TTSNode(bus=bus, synthesizer=synth, **kwargs)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)  # let setup() install the subscriber
    return node, thread


def _stop_node(node, thread):
    node.stop()
    thread.join(timeout=2.0)


# ── happy path ────────────────────────────────────────────────────

def test_speech_command_triggers_synthesizer(bus):
    """A /act/speech message → synthesizer.speak() called with the text."""
    synth = _MockSynth()
    node, thread = _start_node(bus, synth)
    try:
        bus.publish(topics.SpeechCommand(text="hello world"))
        # Synthesizer is invoked on the node tick — give it a tick or two.
        for _ in range(20):
            if synth.calls:
                break
            time.sleep(0.05)
        assert synth.calls == ["hello world"]
    finally:
        _stop_node(node, thread)


def test_successful_speech_publishes_ack_with_correlation_id(bus):
    """After speak() returns ok, /sense/spoken fires with the same
    correlation_id."""
    synth = _MockSynth(result={"spoken": True, "elapsed_s": 0.42})
    node, thread = _start_node(bus, synth)
    cid = uuid.uuid4().hex

    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def on_ack(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_SPOKEN, on_ack)
    try:
        bus.publish(topics.SpeechCommand(text="hi", correlation_id=cid))
        assert event.wait(timeout=2.0), "no SpokenAck published"
        ack = received[0]
        assert isinstance(ack, topics.SpokenAck)
        assert ack.ok is True
        assert ack.duration_s == pytest.approx(0.42)
        assert ack.reason is None
        assert ack.correlation_id == cid
        assert ack.node_id == "tts"
    finally:
        _stop_node(node, thread)


def test_failure_propagates_reason_to_ack(bus):
    """A synthesizer that returns ok=False gets its reason mirrored."""
    synth = _MockSynth(result={
        "spoken": False, "reason": "drain timeout", "elapsed_s": 0.0,
    })
    node, thread = _start_node(bus, synth)

    received = []
    event = threading.Event()

    def on_ack(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_SPOKEN, on_ack)
    try:
        bus.publish(topics.SpeechCommand(text="fail me"))
        assert event.wait(timeout=2.0)
        ack = received[0]
        assert ack.ok is False
        assert ack.reason == "drain timeout"
    finally:
        _stop_node(node, thread)


def test_synthesizer_exception_becomes_failure_ack(bus):
    """If speak() raises, the node catches it and publishes ok=False
    with the exception class + message as the reason."""
    synth = _MockSynth(raise_on_speak=RuntimeError("kokoro exploded"))
    node, thread = _start_node(bus, synth)

    received = []
    event = threading.Event()

    def on_ack(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_SPOKEN, on_ack)
    try:
        bus.publish(topics.SpeechCommand(text="crash test"))
        assert event.wait(timeout=2.0)
        ack = received[0]
        assert ack.ok is False
        assert "RuntimeError" in ack.reason
        assert "kokoro exploded" in ack.reason
    finally:
        _stop_node(node, thread)


# ── backpressure ─────────────────────────────────────────────────

def test_full_queue_immediate_fail_ack(bus):
    """Backpressure: when the node's internal queue is saturated,
    new requests get an immediate ok=False with reason='TTS queue full'
    so the brain doesn't wait for a timeout."""
    # 1-deep queue so it fills instantly.  Slow synth so the worker
    # thread doesn't drain it.
    synth = _MockSynth(delay_s=0.5)
    node, thread = _start_node(bus, synth, queue_maxsize=1)

    received_acks: list[topics.SpokenAck] = []
    received_event = threading.Event()

    def on_ack(msg):
        received_acks.append(msg)
        # Stop after we've seen at least one failure ack.
        if any(not a.ok for a in received_acks):
            received_event.set()

    bus.subscribe(topics.SENSE_SPOKEN, on_ack)
    try:
        # Burst more than queue_maxsize + 1 messages so at least one
        # has to be rejected.  First two get accepted (one drains
        # immediately into the worker, one fills the queue); the
        # third hits the full queue and gets immediate-fail acked.
        for i in range(5):
            bus.publish(topics.SpeechCommand(
                text=f"burst-{i}",
                correlation_id=f"cid-{i}",
            ))
            time.sleep(0.01)
        assert received_event.wait(timeout=2.0), (
            "no failure ack received under backpressure"
        )
        full_acks = [a for a in received_acks if a.reason == "TTS queue full"]
        assert len(full_acks) >= 1, (
            f"expected at least one 'TTS queue full' ack; "
            f"got {[a.reason for a in received_acks]}"
        )
    finally:
        _stop_node(node, thread)


# ── lifecycle ────────────────────────────────────────────────────

def test_teardown_calls_synthesizer_shutdown(bus):
    synth = _MockSynth()
    node, thread = _start_node(bus, synth)
    _stop_node(node, thread)
    assert synth.shutdown_called


def test_node_unsubscribes_on_teardown(bus):
    """After teardown, /act/speech messages don't reach the node
    anymore.  Prevents stale-subscriber leak across multiple node
    lifecycles."""
    synth = _MockSynth()
    node, thread = _start_node(bus, synth)
    _stop_node(node, thread)
    # Publish AFTER stop — call count must not increase.
    bus.publish(topics.SpeechCommand(text="post-stop"))
    time.sleep(0.2)
    assert synth.calls == []


# ── barge-in (SpeechStop) ────────────────────────────────────────


class _StoppableSynth:
    """Mock synth whose speak() blocks until either timeout or stop()."""
    def __init__(self):
        self._stop_event = threading.Event()
        self.stops_received = 0

    def speak(self, text):
        self._stop_event.clear()
        stopped = self._stop_event.wait(timeout=5.0)
        return {
            "spoken": not stopped,
            "elapsed_s": 0.1,
            "reason": "interrupted" if stopped else None,
        }

    def stop(self):
        self.stops_received += 1
        self._stop_event.set()

    def shutdown(self):
        pass


def test_speech_stop_interrupts_in_flight_speak(bus):
    """SpeechStop published mid-speak fires synth.stop() and the
    in-flight speak() returns with the interrupted ack.  Proves the
    voice-loop barge-in primitive works end-to-end through the bus."""
    import uuid
    synth = _StoppableSynth()
    node = TTSNode(bus=bus, synthesizer=synth, name="tts",
                   install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)

    cid = uuid.uuid4().hex
    received: list[topics.TopicMessage] = []
    ack_event = threading.Event()

    def on_ack(msg):
        if msg.correlation_id == cid:
            received.append(msg)
            ack_event.set()

    bus.subscribe(topics.SENSE_SPOKEN, on_ack)
    try:
        bus.publish(topics.SpeechCommand(text="hello", correlation_id=cid))
        # Let the synth's blocking speak() start.
        time.sleep(0.2)
        bus.publish(topics.SpeechStop(reason="test interrupt"))
        # Synth should stop, speak() returns, ack publishes.
        assert ack_event.wait(timeout=2.0), "no interrupted ack received"
        assert synth.stops_received >= 1
        ack = received[0]
        assert ack.ok is False
        assert ack.reason == "interrupted"
        assert ack.correlation_id == cid
    finally:
        node.stop()
        thread.join(timeout=2.0)


def test_speech_stop_without_in_flight_speech_is_safe(bus):
    """A SpeechStop arriving when nothing is playing must not crash
    the node — stop() runs against an idle synth."""
    synth = _StoppableSynth()
    node = TTSNode(bus=bus, synthesizer=synth, name="tts",
                   install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        bus.publish(topics.SpeechStop(reason="idle stop"))
        time.sleep(0.2)
        # stop() still ran (synth recorded it); node still healthy.
        assert synth.stops_received == 1
        assert node.state.value == "running"
    finally:
        node.stop()
        thread.join(timeout=2.0)


def test_speech_stop_with_stale_correlation_id_is_ignored(bus):
    """A correlated stop for an old utterance must not interrupt the
    newer speech currently active in the TTS node."""
    synth = _StoppableSynth()
    node = TTSNode(bus=bus, synthesizer=synth, name="tts",
                   install_signal_handlers=False)
    node._active_correlation_id = "current"

    node._on_speech_stop(topics.SpeechStop(
        reason="stale interrupt",
        correlation_id="old",
    ))

    assert synth.stops_received == 0


def test_speech_stop_synthesizer_without_stop_method_logs_and_continues(bus):
    """If the synthesizer doesn't implement stop() (older Synthesizer
    surface), the node logs but doesn't crash."""
    class _NoStopSynth:
        def speak(self, text):
            return {"spoken": True, "elapsed_s": 0.0}
        # NO stop() method
        def shutdown(self):
            pass

    synth = _NoStopSynth()
    node = TTSNode(bus=bus, synthesizer=synth, name="tts",
                   install_signal_handlers=False)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        bus.publish(topics.SpeechStop(reason="no-op"))
        time.sleep(0.2)
        # Node should still be running.
        assert node.state.value == "running"
    finally:
        node.stop()
        thread.join(timeout=2.0)
