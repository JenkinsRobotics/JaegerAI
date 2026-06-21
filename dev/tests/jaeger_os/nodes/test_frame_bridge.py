"""Tests for the WebSocket FrameBridge — wire-format encoding,
multi-client broadcasting, slow-client dropping.

The bridge runs an asyncio loop on a daemon thread; tests use the
real `websockets` client library to verify end-to-end binary
delivery.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest
import websockets

from jaeger_os.nodes.software.animation import bridge
from jaeger_os.nodes.software.animation.base import FrameBuffer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── wire format ────────────────────────────────────────────────────

def test_encode_then_decode_round_trips() -> None:
    frame = FrameBuffer(
        width=4, height=2,
        data=bytes([1, 2, 3, 4] * 8),
        duration_ms=33,
        is_final=False,
    )
    raw = bridge.encode_frame(frame, asset="faces/smile.json")
    header, pixels = bridge.decode_frame(raw)
    assert header["w"] == 4
    assert header["h"] == 2
    assert header["format"] == "RGBA8"
    assert header["duration_ms"] == 33
    assert header["is_final"] is False
    assert header["asset"] == "faces/smile.json"
    assert pixels == frame.data


def test_truncated_message_raises() -> None:
    with pytest.raises(ValueError):
        bridge.decode_frame(b"\x00\x00")  # only 2 bytes


def test_oversized_header_rejected() -> None:
    """A FrameBuffer with a pathologically long asset would blow the
    header budget — defensive cap raises rather than corrupting wire."""
    # Build a frame with an asset path past the 4 KB header cap.
    huge_asset = "x" * 8192
    frame = FrameBuffer(width=1, height=1, data=b"\x00" * 4)
    with pytest.raises(ValueError):
        bridge.encode_frame(frame, asset=huge_asset)


# ── live server ────────────────────────────────────────────────────

@pytest.fixture
def server():
    port = _free_port()
    srv = bridge.FrameBridge(host="127.0.0.1", port=port)
    srv.start()
    yield srv
    srv.stop()


def test_client_receives_published_frame(server) -> None:
    received: list[bytes] = []
    done = threading.Event()

    async def _client():
        async with websockets.connect(
            f"ws://127.0.0.1:{server.port}/frames",
        ) as ws:
            data = await ws.recv()
            received.append(data)
            done.set()

    def _run_client():
        asyncio.run(_client())

    client_thread = threading.Thread(target=_run_client, daemon=True)
    client_thread.start()
    # Give the client a moment to connect.
    time.sleep(0.3)
    server.publish_frame(FrameBuffer(
        width=2, height=2,
        data=bytes([255, 128, 64, 255] * 4),
        duration_ms=33,
        is_final=False,
    ))
    assert done.wait(timeout=2.0), "no frame received within 2 s"
    header, pixels = bridge.decode_frame(received[0])
    assert header["w"] == 2
    assert header["h"] == 2
    assert pixels[0:4] == bytes([255, 128, 64, 255])
    client_thread.join(timeout=2.0)


def test_two_clients_both_receive(server) -> None:
    barrier = threading.Barrier(2)
    received_a: list[bytes] = []
    received_b: list[bytes] = []

    async def _client(out: list[bytes]):
        async with websockets.connect(
            f"ws://127.0.0.1:{server.port}/frames",
        ) as ws:
            barrier.wait(timeout=2.0)
            out.append(await ws.recv())

    def _run(out):
        asyncio.run(_client(out))

    ta = threading.Thread(target=_run, args=(received_a,), daemon=True)
    tb = threading.Thread(target=_run, args=(received_b,), daemon=True)
    ta.start()
    tb.start()
    # Wait until both clients are connected (via the barrier).
    time.sleep(0.5)
    server.publish_frame(FrameBuffer(
        width=1, height=1,
        data=bytes([10, 20, 30, 40]),
    ))
    ta.join(timeout=2.0)
    tb.join(timeout=2.0)
    assert received_a and received_b
    assert received_a[0] == received_b[0]
