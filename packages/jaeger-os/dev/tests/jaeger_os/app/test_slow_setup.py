"""A node whose setup() is slow must not be mistaken for a dead one.

This is the failure that only appears when something real runs.
Opening the audio device on macOS measures 3.6s (0.8 output, 2.8
input); loading a Whisper model is longer. `alive()` used to mean
`state == RUNNING`, and the watch loop ticks every 0.25s — so exactly
the nodes worth having were declared dead and restarted, forever,
since each restart had the same slow setup.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.app.manifest import NodeSpec
from jaeger_os.app.supervisor import Supervisor, ThreadHandle
from jaeger_os.nodes.base import Node, NodeState
from jaeger_os.transport import InProcBus


class _SlowStarter(Node):
    """Takes a while to come up, like a real device or model."""

    setup_s = 1.0

    def setup(self):
        time.sleep(self.setup_s)

    def tick(self):
        time.sleep(0.05)


class _Crasher(Node):
    def setup(self):
        raise RuntimeError("boom")

    def tick(self):
        time.sleep(0.05)


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _handle(bus, cls, node_id="slow"):
    return ThreadHandle(
        NodeSpec(id=node_id, tier=3, backend="thread"),
        lambda: cls(bus=bus, name=node_id, install_signal_handlers=False))


def test_a_node_still_setting_up_is_alive(bus):
    """The whole bug in one assertion."""
    h = _handle(bus, _SlowStarter)
    t = threading.Thread(target=h.start, daemon=True)
    t.start()
    time.sleep(0.4)          # mid-setup
    try:
        assert h._node is not None and h._node.state == NodeState.SETTING_UP
        assert h.alive(), "a node that is still starting was called dead"
    finally:
        h.stop()
        t.join(timeout=3)


def test_a_slow_node_is_not_restarted(bus):
    """What the operator actually saw: 'node audio_io died; restart in
    1s' for a node that was merely opening a microphone."""
    sup = Supervisor(bus=bus)
    sup.add(_handle(bus, _SlowStarter))
    sup.start_all()
    try:
        time.sleep(1.6)      # through setup and beyond
        h = sup._get("slow")
        assert h.restarts == 0, f"restarted {h.restarts}x during setup"
        assert h.alive()
    finally:
        sup.stop_all()


def test_a_node_that_really_dies_is_still_caught(bus):
    """The fix must not blind the supervisor. A failed setup is dead."""
    h = _handle(bus, _Crasher, node_id="crash")
    h.start()
    time.sleep(0.4)
    assert not h.alive(), "a node whose setup raised was reported alive"


def test_a_stopped_node_is_not_alive(bus):
    h = _handle(bus, _SlowStarter, node_id="stopme")
    _SlowStarter.setup_s = 0.05
    try:
        h.start()
        time.sleep(0.3)
        assert h.alive()
        h.stop()
        assert not h.alive()
    finally:
        _SlowStarter.setup_s = 1.0


def test_a_dead_thread_is_not_alive(bus):
    """If the thread exits for any reason, the node is gone regardless
    of what its last recorded state happened to be."""
    h = _handle(bus, _SlowStarter, node_id="exiting")
    _SlowStarter.setup_s = 0.05
    try:
        h.start()
        time.sleep(0.3)
        h._node.stop()
        h._thread.join(timeout=3)
        assert not h.alive()
    finally:
        _SlowStarter.setup_s = 1.0
