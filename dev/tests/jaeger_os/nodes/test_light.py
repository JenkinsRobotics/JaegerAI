"""Tests for ``jaeger_os.nodes.hardware.light`` — Track C skeleton.

Covers LightNode lifecycle + SerialLightAdapter's universal ASCII
wire format.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes import LightNode, SerialLightAdapter
from jaeger_os.transport import InProcBus


class _MockLight:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.patterns = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send_pattern(self, *, strip_id, rgb, pattern, duration_ms):
        self.patterns.append((strip_id, tuple(rgb), pattern, duration_ms))


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _start_node(bus, adapter, **kwargs):
    node = LightNode(bus=bus, adapter=adapter,
                     install_signal_handlers=False, **kwargs)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)
    return node, thread


def _stop_node(node, thread):
    node.stop()
    thread.join(timeout=2.0)


def test_setup_starts_adapter(bus):
    adapter = _MockLight()
    node, thread = _start_node(bus, adapter)
    try:
        assert adapter.started is True
    finally:
        _stop_node(node, thread)


def test_teardown_stops_adapter(bus):
    adapter = _MockLight()
    node, thread = _start_node(bus, adapter)
    _stop_node(node, thread)
    assert adapter.stopped is True


def test_light_command_calls_adapter(bus):
    adapter = _MockLight()
    node, thread = _start_node(bus, adapter)
    try:
        bus.publish(topics.LightCommand(
            strip_id="ring", rgb=[255, 128, 0],
            pattern="pulse", duration_ms=500,
        ))
        for _ in range(20):
            if adapter.patterns:
                break
            time.sleep(0.05)
        assert adapter.patterns == [
            ("ring", (255, 128, 0), "pulse", 500)
        ]
    finally:
        _stop_node(node, thread)


# ── SerialLightAdapter wire format ───────────────────────────────

def test_serial_adapter_pattern_wire_format():
    captured = []
    adapter = SerialLightAdapter(write_line=captured.append)
    adapter.start()
    try:
        adapter.send_pattern(
            strip_id="ring", rgb=[255, 128, 0],
            pattern="pulse", duration_ms=500,
        )
        assert captured == [b"LED ring 255 128 0 pulse 500\n"]
    finally:
        adapter.stop()


def test_serial_adapter_off_pattern_uses_off_line():
    """A pattern='off' message gets its own OFF line so firmware
    doesn't have to interpret 'pulse' with all-zeros RGB."""
    captured = []
    adapter = SerialLightAdapter(write_line=captured.append)
    adapter.start()
    try:
        adapter.send_pattern(
            strip_id="ring", rgb=[0, 0, 0],
            pattern="off", duration_ms=0,
        )
        assert captured == [b"OFF ring\n"]
    finally:
        adapter.stop()


def test_serial_adapter_blanks_all_strips_on_close():
    """Safety: closing the adapter sends an OFF * broadcast to blank
    every strip on shutdown.  No 'still glowing after crash' UX."""
    captured = []
    adapter = SerialLightAdapter(write_line=captured.append)
    adapter.start()
    adapter.stop()
    assert b"OFF *\n" in captured


def test_serial_adapter_rejects_wrong_rgb_shape():
    adapter = SerialLightAdapter(write_line=lambda b: None)
    adapter.start()
    with pytest.raises(ValueError):
        adapter.send_pattern(
            strip_id="ring", rgb=[255, 128],  # missing blue
            pattern="solid", duration_ms=0,
        )
    adapter.stop()
