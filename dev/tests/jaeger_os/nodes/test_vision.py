"""Tests for ``jaeger_os.nodes.hardware.vision`` — Track B.5.

Covers:
  * VisionNode lifecycle with a mock adapter (no cv2, no socket)
  * Frame publishing on /sense/camera_frame
  * TCP adapter's length-prefixed wire format via a loopback socket

USB adapter integration test (cv2.VideoCapture against a real
camera) runs out-of-band when an operator has hardware attached —
not autonomous-safe.
"""

from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes import VisionNode
from jaeger_os.nodes.hardware.vision.adapters import FrameEnvelope, TCPCameraAdapter
from jaeger_os.transport import InProcBus


# ── mock adapter ──────────────────────────────────────────────────

class _MockCamera:
    """Drop-in for the CameraAdapter Protocol — feeds canned frames."""

    def __init__(self):
        self.started = False
        self.stopped = False
        self._frames: list[FrameEnvelope] = []
        self._lock = threading.Lock()

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def next_frame(self, timeout=1.0):
        deadline = time.monotonic() + (timeout or 0.0)
        while time.monotonic() < deadline:
            with self._lock:
                if self._frames:
                    return self._frames.pop(0)
            time.sleep(0.01)
        return None

    def feed(self, env: FrameEnvelope):
        with self._lock:
            self._frames.append(env)


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _start_node(bus, adapter, **kwargs):
    node = VisionNode(
        bus=bus, adapter=adapter,
        install_signal_handlers=False, **kwargs,
    )
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)
    return node, thread


def _stop_node(node, thread):
    node.stop()
    thread.join(timeout=2.0)


# ── lifecycle ────────────────────────────────────────────────────

def test_setup_starts_adapter(bus):
    cam = _MockCamera()
    node, thread = _start_node(bus, cam)
    try:
        assert cam.started is True
    finally:
        _stop_node(node, thread)


def test_teardown_stops_adapter(bus):
    cam = _MockCamera()
    node, thread = _start_node(bus, cam)
    _stop_node(node, thread)
    assert cam.stopped is True


def test_adapter_stop_exception_doesnt_block_teardown(bus):
    class _BadStop(_MockCamera):
        def stop(self):
            raise RuntimeError("camera stuck")
    cam = _BadStop()
    node, thread = _start_node(bus, cam)
    _stop_node(node, thread)


# ── frame publishing ─────────────────────────────────────────────

def test_frame_becomes_camera_frame_message(bus):
    cam = _MockCamera()
    received: list[topics.CameraFrame] = []
    event = threading.Event()

    def on_frame(msg):
        received.append(msg)
        event.set()

    bus.subscribe(topics.SENSE_CAMERA_FRAME, on_frame)
    node, thread = _start_node(bus, cam, camera_id="test-cam")
    try:
        cam.feed(FrameEnvelope(
            width=640, height=480, encoding="jpeg",
            data=b"\xff\xd8\xff" + b"\x00" * 32,
        ))
        assert event.wait(timeout=2.0)
        msg = received[0]
        assert isinstance(msg, topics.CameraFrame)
        assert msg.image_w == 640
        assert msg.image_h == 480
        assert msg.encoding == "jpeg"
        assert msg.frame_bytes.startswith(b"\xff\xd8\xff")
        assert msg.camera_id == "test-cam"
        assert msg.frame_seq == 1
        assert msg.node_id == "vision"
    finally:
        _stop_node(node, thread)


def test_frame_seq_monotonic_across_frames(bus):
    cam = _MockCamera()
    received: list[int] = []
    target = threading.Event()

    def on_frame(msg):
        received.append(msg.frame_seq)
        if len(received) >= 3:
            target.set()

    bus.subscribe(topics.SENSE_CAMERA_FRAME, on_frame)
    node, thread = _start_node(bus, cam)
    try:
        for _ in range(3):
            cam.feed(FrameEnvelope(
                width=320, height=240, encoding="jpeg", data=b"f",
            ))
        assert target.wait(timeout=3.0), f"only got {received}"
        assert received[:3] == [1, 2, 3]
    finally:
        _stop_node(node, thread)


def test_no_frame_no_publish(bus):
    cam = _MockCamera()
    received = []

    def on_frame(msg):
        received.append(msg)

    bus.subscribe(topics.SENSE_CAMERA_FRAME, on_frame)
    node, thread = _start_node(bus, cam, poll_timeout_s=0.05)
    try:
        time.sleep(0.2)
        assert received == []
    finally:
        _stop_node(node, thread)


# ── TCP adapter wire format (loopback) ────────────────────────────

class _TCPFrameServer:
    """Tiny TCP server that pushes length-prefixed frames at a
    connected client.  Used in tests to exercise TCPCameraAdapter
    without depending on JP01-specific producers."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(1)
        self._port = self._server.getsockname()[1]
        self._client: socket.socket | None = None
        self._stop = threading.Event()
        self._frames: list[bytes] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._port

    def push(self, payload: bytes):
        with self._lock:
            self._frames.append(payload)

    def stop(self):
        self._stop.set()
        try:
            self._server.close()
        except Exception:
            pass
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    def _loop(self):
        self._server.settimeout(2.0)
        try:
            self._client, _ = self._server.accept()
        except OSError:
            return
        while not self._stop.is_set():
            with self._lock:
                to_send = self._frames[:]
                self._frames.clear()
            for payload in to_send:
                try:
                    self._client.sendall(struct.pack("!I", len(payload)))
                    self._client.sendall(payload)
                except OSError:
                    return
            time.sleep(0.02)


def test_tcp_adapter_round_trips_length_prefixed_frame():
    """A frame pushed by a length-prefixed TCP producer comes out
    of TCPCameraAdapter.next_frame() with the same bytes."""
    server = _TCPFrameServer()
    payload = b"\xff\xd8\xff" + b"\xaa" * 128
    adapter = TCPCameraAdapter(host="127.0.0.1", port=server.port)
    try:
        adapter.start()
        # Server pushes after the adapter connects.
        time.sleep(0.1)
        server.push(payload)
        frame = adapter.next_frame(timeout=2.0)
        assert frame is not None, "no frame received"
        assert frame.encoding == "jpeg"
        assert frame.data == payload
    finally:
        adapter.stop()
        server.stop()


def test_tcp_adapter_handles_implausibly_large_length():
    """A wire frame claiming >64MB is treated as corruption (OSError)
    rather than swallowed silently."""
    server = _TCPFrameServer()
    adapter = TCPCameraAdapter(host="127.0.0.1", port=server.port,
                                recv_timeout_s=0.5)
    try:
        adapter.start()
        time.sleep(0.1)
        # Send a malformed length manually
        assert server._client is not None
        server._client.sendall(struct.pack("!I", 200 * 1024 * 1024))
        time.sleep(0.5)
        # Recv loop should have died.  next_frame returns None.
        frame = adapter.next_frame(timeout=0.5)
        assert frame is None
    finally:
        adapter.stop()
        server.stop()
