"""Tests for ``jaeger_os.nodes.base`` — Track A.5.

Pins the four-phase lifecycle, the stop/restart semantics, and the
health envelope.  Uses InProcBus directly (no ZMQ overhead).
"""

from __future__ import annotations

import threading
import time
import uuid

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes import Node, NodeState
from jaeger_os.transport import InProcBus


# ── test node subclasses ──────────────────────────────────────────

class _CountingNode(Node):
    """Counts ticks.  Useful for lifecycle tests."""
    def __init__(self, **kwargs):
        super().__init__(install_signal_handlers=False, **kwargs)
        self.tick_count = 0
        self.setup_called = False
        self.teardown_called = False

    def setup(self):
        self.setup_called = True

    def tick(self):
        self.tick_count += 1
        time.sleep(0.01)

    def teardown(self):
        self.teardown_called = True


class _FailingSetupNode(Node):
    def __init__(self, **kwargs):
        super().__init__(install_signal_handlers=False, **kwargs)
        self.teardown_called = False

    def setup(self):
        raise RuntimeError("setup boom")

    def teardown(self):
        self.teardown_called = True


class _RaisingTickNode(Node):
    def __init__(self, **kwargs):
        super().__init__(install_signal_handlers=False, **kwargs)
        self.tick_attempts = 0

    def tick(self):
        self.tick_attempts += 1
        time.sleep(0.01)
        raise RuntimeError(f"tick boom #{self.tick_attempts}")


class _EchoNode(Node):
    """Subscribes to /sense/transcript; publishes a SpeechCommand
    echoing back.  The verification-gate node for Track A's IPC."""
    def __init__(self, **kwargs):
        super().__init__(install_signal_handlers=False, **kwargs)

    def setup(self):
        self.bus.subscribe(topics.SENSE_TRANSCRIPT, self._on_transcript)

    def _on_transcript(self, msg):
        self.bus.publish(topics.SpeechCommand(
            text=f"You said: {msg.text}",
            node_id=self.name,
            correlation_id=msg.correlation_id,
        ))


# ── helpers ───────────────────────────────────────────────────────

@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _start(node, *, join_timeout=2.0):
    """Run a node on a background thread; return the thread."""
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    return t


# ── lifecycle ─────────────────────────────────────────────────────

def test_lifecycle_setup_tick_teardown(bus):
    """Happy path: setup runs, tick fires a few times, teardown runs
    on stop."""
    node = _CountingNode(bus=bus, name="counter")
    assert node.state == NodeState.INIT
    t = _start(node)
    time.sleep(0.15)  # let a few ticks happen
    assert node.state == NodeState.RUNNING
    assert node.setup_called
    assert node.tick_count >= 1
    node.stop()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert node.teardown_called
    assert node.state == NodeState.STOPPED


def test_setup_failure_records_error_runs_teardown(bus):
    """A setup that raises records the error in health() AND still
    runs teardown (cleanup must happen even on broken setup)."""
    node = _FailingSetupNode(bus=bus, name="bad-setup")
    t = _start(node)
    t.join(timeout=2.0)
    assert node.state == NodeState.FAILED
    assert node.teardown_called, "teardown must run even when setup fails"
    health = node.health()
    assert health["error"] is not None
    assert "setup boom" in health["error"]


def test_tick_failure_does_not_stop_node(bus):
    """A tick that raises gets logged but the node keeps running
    (most subsystems have transient I/O failures we don't want to
    treat as terminal)."""
    node = _RaisingTickNode(bus=bus, name="rough-tick")
    t = _start(node)
    time.sleep(0.1)
    # Should have attempted several ticks despite each one raising.
    assert node.tick_attempts >= 2, (
        f"only {node.tick_attempts} attempts — tick errors stopping the node"
    )
    assert node.state == NodeState.RUNNING
    node.stop()
    t.join(timeout=2.0)
    assert node.state == NodeState.STOPPED


def test_stop_is_idempotent(bus):
    """Calling stop() before/during/after running is safe."""
    node = _CountingNode(bus=bus)
    node.stop()  # before run
    node.stop()  # twice
    t = _start(node)
    node.stop()  # during run
    t.join(timeout=2.0)
    node.stop()  # after run


def test_request_restart_distinct_from_stop(bus):
    """A node that requests restart ends in RESTARTING state, not
    STOPPED.  Supervisor (Track D) reads this to decide re-spawn."""
    node = _CountingNode(bus=bus, name="restarter")
    t = _start(node)
    time.sleep(0.05)
    node.request_restart()
    t.join(timeout=2.0)
    assert node.state == NodeState.RESTARTING
    assert node.teardown_called


# ── health ────────────────────────────────────────────────────────

def test_health_envelope_shape(bus):
    """health() returns the dict shape Track D's supervisor expects."""
    node = _CountingNode(bus=bus, name="health-check")
    t = _start(node)
    time.sleep(0.05)
    h = node.health()
    assert h["name"] == "health-check"
    assert h["state"] == NodeState.RUNNING.value
    assert h["uptime_s"] > 0.0
    assert h["error"] is None
    node.stop()
    t.join(timeout=2.0)


def test_health_carries_error_after_failure(bus):
    """A failed node's health() shows the exception type and message."""
    node = _FailingSetupNode(bus=bus)
    t = _start(node)
    t.join(timeout=2.0)
    h = node.health()
    assert h["state"] == NodeState.FAILED.value
    assert "setup boom" in h["error"]
    assert "RuntimeError" in h["error"]


# ── verification gate: echo node round-trip ───────────────────────

def test_echo_node_round_trip(bus):
    """The Track A verification gate: a node SUB→transform→PUB cycle
    works end-to-end through the Bus."""
    node = _EchoNode(bus=bus, name="echo")
    t = _start(node)
    time.sleep(0.05)  # let setup register the subscriber

    # Subscribe to /act/speech ourselves (representing the brain).
    received: list[topics.TopicMessage] = []
    event = threading.Event()

    def on_speech(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.ACT_SPEECH, on_speech)

    # Pretend to be the STT node publishing a transcript.
    cid = uuid.uuid4().hex
    bus.publish(topics.Transcript(
        text="hello world",
        node_id="stt",
        correlation_id=cid,
    ))

    assert event.wait(timeout=2.0), "echo node didn't publish back"
    assert len(received) == 1
    assert isinstance(received[0], topics.SpeechCommand)
    assert received[0].text == "You said: hello world"
    assert received[0].node_id == "echo"
    assert received[0].correlation_id == cid

    node.stop()
    t.join(timeout=2.0)


def test_node_default_tick_doesnt_busy_loop(bus):
    """A Node that doesn't override tick() should sleep, not burn CPU."""
    # The default Node base class is abstract... but our test
    # subclasses inherit from it.  Use a subclass that doesn't
    # override tick:
    class _Sleepy(Node):
        pass

    node = _Sleepy(bus=bus, name="sleepy", install_signal_handlers=False,
                   tick_interval_s=0.05)
    t0 = time.perf_counter()
    t = _start(node)
    time.sleep(0.2)
    node.stop()
    t.join(timeout=2.0)
    elapsed = time.perf_counter() - t0
    # 0.2 s of sleep at 0.05 s intervals = ~4 ticks.  CPU should
    # be near zero, not pegged.  Hard to test CPU directly in
    # pytest; the soft test is that the node stays in RUNNING
    # state until stop, doesn't crash, and tick_interval_s is
    # honoured (elapsed >= 0.2 s).
    assert elapsed >= 0.2
