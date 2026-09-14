"""A node whose device link died must not report healthy.

The failure this closes produces no symptom: a driver whose serial
link goes away keeps ticking happily and reports RUNNING forever,
because the tick loop is fine. It is the LINK that is gone, and
nothing else in the system can tell.

"The node is running" and "the motor controller is answering" are
different facts. Only the second means the robot is alive.

Taken from Quantum Codex, where every device must implement
`get_ste_comm_valid()`.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os import Node, topics
from jaeger_os.transport import InProcBus


class _Plain(Node):
    """Owns no device — the common case."""

    def tick(self):
        time.sleep(0.05)


class _Driver(Node):
    """Owns a device whose link can go away."""

    connected = True

    def link_ok(self) -> bool:
        return self.connected

    def tick(self):
        time.sleep(0.05)


class _BrokenCheck(Node):
    def link_ok(self) -> bool:
        raise OSError("serial port vanished")

    def tick(self):
        time.sleep(0.05)


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _run(node):
    t = threading.Thread(target=node.run, daemon=True)
    t.start()
    time.sleep(0.3)
    return t


def _heartbeats(bus, node, seconds=1.4):
    got = []
    bus.subscribe(topics.SYS_NODE_HEALTH, got.append)
    time.sleep(0.15)
    t = _run(node)
    try:
        deadline = time.monotonic() + seconds
        while not got and time.monotonic() < deadline:
            time.sleep(0.02)
        return got
    finally:
        node.stop()
        t.join(timeout=2)


# ── the default: not a device node ───────────────────────────────

def test_a_node_with_no_device_is_not_reported_disconnected(bus):
    """link_connected was hardcoded False, so EVERY node in the system
    looked disconnected and the field was worthless."""
    got = _heartbeats(bus, _Plain(bus=bus, name="plain",
                                  install_signal_handlers=False))
    assert got, "no heartbeat"
    assert got[0].link_connected is True
    assert got[0].level == topics.HEALTH_OK


def test_link_ok_defaults_to_not_applicable(bus):
    assert _Plain(bus=bus, name="p",
                  install_signal_handlers=False).link_ok() is None


# ── a live link ──────────────────────────────────────────────────

def test_a_connected_driver_is_ok(bus):
    node = _Driver(bus=bus, name="drv", install_signal_handlers=False)
    node.connected = True
    got = _heartbeats(bus, node)
    assert got[0].link_connected is True
    assert got[0].level == topics.HEALTH_OK


# ── the failure this exists for ──────────────────────────────────

def test_a_dead_link_is_ERROR_not_running_and_fine(bus):
    """The whole point. The node is alive, ticking, and useless."""
    node = _Driver(bus=bus, name="drv", install_signal_handlers=False)
    node.connected = False
    got = _heartbeats(bus, node)
    assert got[0].state == "running", "the node really is still running"
    assert got[0].link_connected is False
    assert got[0].level == topics.HEALTH_ERROR, (
        "a driver that cannot reach its device is not degraded, it is "
        "not doing its job")
    assert "link" in got[0].detail


def test_a_dead_link_is_error_not_warning(bus):
    """WARN is how a dead robot looks healthy on a dashboard."""
    node = _Driver(bus=bus, name="drv", install_signal_handlers=False)
    node.connected = False
    assert node.health_level() == topics.HEALTH_ERROR
    assert node.health_level() != topics.HEALTH_WARN


def test_a_link_check_that_raises_counts_as_down(bus):
    """A check that throws is a link that is gone — and it must not
    take out the heartbeat carrying that news."""
    node = _BrokenCheck(bus=bus, name="broken", install_signal_handlers=False)
    got = _heartbeats(bus, node)
    assert got, "the heartbeat died with the link check"
    assert got[0].link_connected is False
    assert got[0].level == topics.HEALTH_ERROR


def test_the_system_level_reflects_a_dead_link(bus):
    """One driver offline must show in the aggregate, or an operator
    watching the system sees green."""
    from jaeger_os.app.health import HealthCache

    cache = HealthCache(bus)
    node = _Driver(bus=bus, name="drv", install_signal_handlers=False)
    node.connected = False
    _heartbeats(bus, node)
    time.sleep(0.2)
    assert cache.system_level() == topics.HEALTH_ERROR
