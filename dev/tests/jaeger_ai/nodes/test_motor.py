"""Tests for ``jaeger_os.nodes.motor`` — Track C skeleton.

Covers MotorNode lifecycle + SerialMotorAdapter's universal ASCII
wire format.  Instance-specific board adapters (JP01-MC01 ESP32,
etc.) get their own tests when wired up.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes import MotorNode, SerialMotorAdapter
from jaeger_os.transport import InProcBus


# ── mock adapter ─────────────────────────────────────────────────

class _MockMotor:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.velocities = []
        self.waypoints = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send_velocity(self, *, linear_x_mps, linear_y_mps,
                       angular_z_rps, duration_s):
        self.velocities.append(
            (linear_x_mps, linear_y_mps, angular_z_rps, duration_s)
        )

    def send_waypoint(self, *, target_xy):
        self.waypoints.append(tuple(target_xy))


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _start_node(bus, adapter, **kwargs):
    node = MotorNode(bus=bus, adapter=adapter,
                     install_signal_handlers=False, **kwargs)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)
    return node, thread


def _stop_node(node, thread):
    node.stop()
    thread.join(timeout=2.0)


# ── lifecycle ────────────────────────────────────────────────────

def test_setup_starts_adapter(bus):
    adapter = _MockMotor()
    node, thread = _start_node(bus, adapter)
    try:
        assert adapter.started is True
    finally:
        _stop_node(node, thread)


def test_teardown_stops_adapter(bus):
    adapter = _MockMotor()
    node, thread = _start_node(bus, adapter)
    _stop_node(node, thread)
    assert adapter.stopped is True


# ── command routing ─────────────────────────────────────────────

def test_velocity_command_calls_adapter(bus):
    adapter = _MockMotor()
    node, thread = _start_node(bus, adapter)
    try:
        bus.publish(topics.MotionCommand(
            linear_x_mps=0.5, linear_y_mps=0.0,
            angular_z_rps=0.1, duration_s=2.0,
        ))
        for _ in range(20):
            if adapter.velocities:
                break
            time.sleep(0.05)
        assert adapter.velocities == [(0.5, 0.0, 0.1, 2.0)]
        assert adapter.waypoints == []
    finally:
        _stop_node(node, thread)


def test_waypoint_command_calls_adapter(bus):
    adapter = _MockMotor()
    node, thread = _start_node(bus, adapter)
    try:
        bus.publish(topics.MotionCommand(
            use_waypoint=True, target_xy=[1.0, 2.0],
        ))
        for _ in range(20):
            if adapter.waypoints:
                break
            time.sleep(0.05)
        assert adapter.waypoints == [(1.0, 2.0)]
        assert adapter.velocities == []
    finally:
        _stop_node(node, thread)


# ── SerialMotorAdapter wire format ───────────────────────────────

def test_serial_adapter_velocity_wire_format():
    captured = []
    adapter = SerialMotorAdapter(write_line=captured.append)
    adapter.start()
    try:
        adapter.send_velocity(
            linear_x_mps=0.5, linear_y_mps=0.25,
            angular_z_rps=0.1, duration_s=2.0,
        )
        assert captured == [b"VEL 0.5000 0.2500 0.1000 2.0000\n"]
    finally:
        adapter.stop()


def test_serial_adapter_waypoint_wire_format():
    captured = []
    adapter = SerialMotorAdapter(write_line=captured.append)
    adapter.start()
    try:
        adapter.send_waypoint(target_xy=[1.5, -2.0])
        assert captured == [b"WP 1.5000 -2.0000\n"]
    finally:
        adapter.stop()


def test_serial_adapter_stops_motion_on_close():
    """Safety: closing the adapter sends STOP so a crashed node
    doesn't leave the robot rolling."""
    captured = []
    adapter = SerialMotorAdapter(write_line=captured.append)
    adapter.start()
    adapter.stop()
    assert b"STOP\n" in captured


def test_serial_adapter_waypoint_rejects_wrong_shape():
    adapter = SerialMotorAdapter(write_line=lambda b: None)
    adapter.start()
    with pytest.raises(ValueError):
        adapter.send_waypoint(target_xy=[1.0])  # missing y
    adapter.stop()
