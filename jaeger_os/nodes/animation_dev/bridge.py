"""WebSocket bridge — ship :class:`FrameBuffer` frames from the
AnimationNode to the Swift renderer (mochi/interfaces/avatar/) or any
other WebSocket-speaking client.

Wire format documented in
``dev/docs/0.5.0_swift_renderer_plan.md``:

    [ 4-byte BE length L ]
    [ L bytes UTF-8 JSON header ]
    [ width * height * 4 bytes RGBA8 pixel data ]

Header schema:
    {
      "w":  int,
      "h":  int,
      "format": "RGBA8",
      "duration_ms": int,
      "is_final": bool,
      "asset": str
    }

Usage::

    from jaeger_os.nodes.animation_dev import bridge

    server = bridge.FrameBridge(host="127.0.0.1", port=8765)
    server.start()
    # Pass server.publish_frame as the AnimationNode's frame_callback:
    animation_node = AnimationNode(bus=bus,
                                   frame_callback=server.publish_frame)

The bridge runs an asyncio loop on a daemon thread; ``publish_frame``
is callable from any thread (it pumps into a queue the loop drains).
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from .base import FrameBuffer


# JSON header is small — bounded so a deformed FrameBuffer can't
# blow the bridge.  Real headers are ~80-120 bytes.
_MAX_HEADER_BYTES = 4096


class FrameBridge:
    """Background WebSocket server that broadcasts FrameBuffers.

    Multiple clients can connect — useful for an OBS browser source
    AND a local renderer.  Each client gets every frame; slow clients
    are dropped rather than back-pressuring the animation loop (the
    animation loop is realtime; dropped clients can reconnect).
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        path: str = "/frames",
    ) -> None:
        self.host = host
        self.port = port
        self.path = path
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server_started = threading.Event()
        self._stop_event = threading.Event()
        self._clients: set[ServerConnection] = set()
        self._clients_lock = threading.Lock()

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self, *, ready_timeout_s: float = 5.0) -> None:
        """Spin up the server on a daemon thread.  Blocks until the
        listener is bound (or ``ready_timeout_s`` elapses)."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"animation-bridge-{self.port}",
            daemon=True,
        )
        self._thread.start()
        if not self._server_started.wait(timeout=ready_timeout_s):
            raise RuntimeError(
                f"FrameBridge failed to bind {self.host}:{self.port} "
                f"within {ready_timeout_s}s"
            )

    def stop(self, *, timeout_s: float = 5.0) -> None:
        """Tear down the loop + thread.  Idempotent."""
        if self._loop is None or self._thread is None:
            return
        self._stop_event.set()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout_s)
        self._loop = None
        self._thread = None
        self._server_started.clear()
        with self._clients_lock:
            self._clients.clear()

    # ── frame publishing ──────────────────────────────────────────

    def publish_frame(self, frame: FrameBuffer) -> None:
        """Serialise + broadcast a FrameBuffer.  Thread-safe — call
        from the AnimationNode's render thread or anywhere else."""
        if self._loop is None:
            return
        try:
            message = encode_frame(frame, asset="")
        except Exception:  # noqa: BLE001
            return
        self._loop.call_soon_threadsafe(self._enqueue, message)

    def _enqueue(self, message: bytes) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            # Best-effort broadcast.  A slow client can't wedge the
            # loop; we schedule the send and forget.
            asyncio.ensure_future(self._send_or_drop(client, message))

    async def _send_or_drop(
        self, client: ServerConnection, message: bytes,
    ) -> None:
        try:
            await client.send(message)
        except Exception:  # noqa: BLE001
            with self._clients_lock:
                self._clients.discard(client)
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass

    # ── server inner loop ─────────────────────────────────────────

    def _run_loop(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception:  # noqa: BLE001
            pass

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        async with serve(self._on_client, self.host, self.port):
            self._server_started.set()
            # Wait until stop() is called.
            stop_future = asyncio.Future()

            def _signal() -> None:
                if not stop_future.done():
                    stop_future.set_result(None)

            self._loop.run_in_executor(None, self._wait_for_stop_signal,
                                        _signal)
            await stop_future

    def _wait_for_stop_signal(self, signal_fn) -> None:
        # Blocking wait on the threading.Event; the loop schedules
        # the signal back via the call we passed in.
        self._stop_event.wait()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(signal_fn)

    async def _on_client(self, client: ServerConnection) -> None:
        """Per-connection handler — adds the client to the broadcast
        set, blocks until the client disconnects."""
        if client.request and self.path not in (
            client.request.path or "/"
        ):
            await client.close(code=1008, reason="bad path")
            return
        with self._clients_lock:
            self._clients.add(client)
        try:
            # Keep the connection open; we only PUSH frames.
            # Reading drains any pings the client sends.
            async for _ in client:
                pass
        except websockets.ConnectionClosed:
            pass
        finally:
            with self._clients_lock:
                self._clients.discard(client)


# ── wire format helpers ───────────────────────────────────────────

def encode_frame(frame: FrameBuffer, *, asset: str = "") -> bytes:
    """Build the binary WebSocket message:
    ``[4-byte BE length][JSON header][pixel data]``.

    Raises ``ValueError`` if the header exceeds the bounded max
    (defensive — keeps malformed FrameBuffers from blowing the
    wire format)."""
    header_obj = {
        "w": int(frame.width),
        "h": int(frame.height),
        "format": "RGBA8",
        "duration_ms": int(frame.duration_ms),
        "is_final": bool(frame.is_final),
        "asset": asset,
    }
    header_bytes = json.dumps(header_obj, separators=(",", ":")).encode("utf-8")
    if len(header_bytes) > _MAX_HEADER_BYTES:
        raise ValueError(
            f"frame header exceeds {_MAX_HEADER_BYTES} bytes"
        )
    return (
        struct.pack(">I", len(header_bytes))
        + header_bytes
        + frame.data
    )


def decode_frame(message: bytes) -> tuple[dict, bytes]:
    """Inverse of :func:`encode_frame` — returns (header, pixels).
    Used by tests + future Python clients."""
    if len(message) < 4:
        raise ValueError("truncated frame: missing length prefix")
    (header_len,) = struct.unpack(">I", message[:4])
    if len(message) < 4 + header_len:
        raise ValueError("truncated frame: header underrun")
    header = json.loads(message[4:4 + header_len].decode("utf-8"))
    pixels = message[4 + header_len:]
    return header, pixels
