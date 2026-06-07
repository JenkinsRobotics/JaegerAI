"""adapters.py — camera adapters for the vision node.

Three building blocks here:

* :class:`FrameEnvelope` — the tuple-like payload an adapter returns.
  Decoupled from the :class:`CameraFrame` topic schema so the
  adapter doesn't import from ``topics`` (lets us add transport-
  agnostic adapters later without circular imports).
* :class:`CameraAdapter` — the Protocol the vision node depends on.
* :class:`USBCameraAdapter` — OpenCV-backed local camera capture.
* :class:`TCPCameraAdapter` — generic length-prefixed TCP frame
  receiver.  The wire format is intentionally vanilla
  (4-byte big-endian length, then that many bytes of encoded image)
  so any producer that speaks the same simple protocol works
  without JROS having to learn vendor-specific formats.  Specific
  hardware integrations (JP01-VCC01 Jetson) land at INSTANCE level
  with their own adapter subclass or per-instance wrapper.
"""

from __future__ import annotations

import queue
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class FrameEnvelope:
    """One captured frame ready to publish.

    ``encoding`` matches :class:`CameraFrame.encoding`:
        - "jpeg"      — encoded JPEG bytes (most universal)
        - "png"       — encoded PNG bytes (lossless)
        - "raw_bgr8"  — raw 8-bit BGR (OpenCV's native layout)
        - "raw_rgb8"  — raw 8-bit RGB
    """
    width: int
    height: int
    encoding: str
    data: bytes


class CameraAdapter(Protocol):
    """The interface the vision node depends on.

    Production: :class:`USBCameraAdapter` or :class:`TCPCameraAdapter`.
    Tests: any object exposing these three methods.

    Adapters MUST be safe to call ``stop()`` on without ``start()``
    having been called — defensive cleanup in node teardown can
    fire before setup finishes if init raises.
    """

    def start(self) -> None:
        """Open the camera / connect the stream."""
        ...

    def stop(self) -> None:
        """Close the camera / disconnect the stream.  Should not
        raise on idempotent re-call."""
        ...

    def next_frame(self, timeout: float | None = 1.0) -> FrameEnvelope | None:
        """Block up to ``timeout`` seconds for the next captured frame.
        Returns ``None`` on timeout — the vision node treats that as
        "no work this tick" and loops back."""
        ...


# ── USB camera (OpenCV) ──────────────────────────────────────────

class USBCameraAdapter:
    """Local USB camera via :mod:`cv2.VideoCapture`.

    OpenCV is the universal abstraction for USB camera capture
    across macOS / Linux / Windows — JROS depends on it lazily
    (import happens in :meth:`start`) so test suites that don't
    exercise vision don't pay the cv2 install cost.

    Frame rate is whatever the camera + driver delivers; the
    adapter polls in a background thread and drops frames if the
    consumer can't keep up (the node's tick may not always be
    waiting).  Latest-frame-wins semantics — we keep a queue of
    size 1 so the node always sees the FRESHEST frame, not a
    stale backlog.
    """

    def __init__(
        self,
        *,
        device_index: int = 0,
        encoding: str = "jpeg",
        target_fps: float = 10.0,
        jpeg_quality: int = 80,
    ) -> None:
        if encoding not in ("jpeg", "png", "raw_bgr8", "raw_rgb8"):
            raise ValueError(
                f"USBCameraAdapter: unsupported encoding {encoding!r}"
            )
        self._device_index = device_index
        self._encoding = encoding
        self._target_fps = target_fps
        self._jpeg_quality = jpeg_quality
        self._cap: Any = None
        self._cv2: Any = None
        # Queue size 1 = latest-frame-wins.  The capture loop
        # overwrites the slot rather than queueing backlog.
        self._latest: "queue.Queue[FrameEnvelope]" = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None

    def start(self) -> None:
        import cv2  # local import — vision is optional
        self._cv2 = cv2
        self._cap = cv2.VideoCapture(self._device_index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"USBCameraAdapter: failed to open camera index "
                f"{self._device_index}"
            )
        self._stop_event.clear()
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"vision-usb-{self._device_index}",
            daemon=True,
        )
        self._capture_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._capture_thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._capture_thread = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    def next_frame(self, timeout: float | None = 1.0) -> FrameEnvelope | None:
        try:
            return self._latest.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── capture loop ─────────────────────────────────────────────

    def _capture_loop(self) -> None:
        period_s = 1.0 / max(0.1, self._target_fps)
        while not self._stop_event.is_set():
            t0 = time.perf_counter()
            ok, frame = self._cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            envelope = self._encode(frame)
            if envelope is None:
                continue
            # Latest-frame-wins: drain the queue slot if a stale
            # frame is still sitting there, then push.
            try:
                self._latest.get_nowait()
            except queue.Empty:
                pass
            try:
                self._latest.put_nowait(envelope)
            except queue.Full:
                pass  # consumer was filling exactly between drain + push
            # Pace to target FPS.
            elapsed = time.perf_counter() - t0
            remaining = period_s - elapsed
            if remaining > 0:
                if self._stop_event.wait(timeout=remaining):
                    return

    def _encode(self, frame_bgr) -> FrameEnvelope | None:
        cv2 = self._cv2
        h, w = frame_bgr.shape[:2]
        enc = self._encoding
        if enc == "jpeg":
            params = [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
            ok, buf = cv2.imencode(".jpg", frame_bgr, params)
            if not ok:
                return None
            return FrameEnvelope(width=w, height=h, encoding="jpeg",
                                  data=bytes(buf))
        if enc == "png":
            ok, buf = cv2.imencode(".png", frame_bgr)
            if not ok:
                return None
            return FrameEnvelope(width=w, height=h, encoding="png",
                                  data=bytes(buf))
        if enc == "raw_bgr8":
            return FrameEnvelope(width=w, height=h, encoding="raw_bgr8",
                                  data=frame_bgr.tobytes())
        if enc == "raw_rgb8":
            return FrameEnvelope(
                width=w, height=h, encoding="raw_rgb8",
                data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB).tobytes(),
            )
        return None


# ── TCP frame stream (generic) ───────────────────────────────────

class TCPCameraAdapter:
    """Camera frames over TCP.

    Generic length-prefixed protocol:

        [4-byte big-endian uint32: payload length]
        [N bytes: encoded image data]

    The producer side speaks the same simple protocol — JP01-VCC01
    today, anything else tomorrow.  Per-vendor wire formats live in
    INSTANCE-level adapter subclasses, not here.

    ``width`` / ``height`` aren't part of the wire envelope by
    design — they default to 0 and the adapter can be subclassed
    to extract them from the encoded bytes (e.g. JPEG header parse)
    when an instance-specific producer doesn't supply them.  Keeps
    the universal protocol payload-only.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 9001,
        encoding: str = "jpeg",
        connect_timeout_s: float = 5.0,
        recv_timeout_s: float = 1.0,
    ) -> None:
        if encoding not in ("jpeg", "png", "raw_bgr8", "raw_rgb8"):
            raise ValueError(
                f"TCPCameraAdapter: unsupported encoding {encoding!r}"
            )
        self._host = host
        self._port = port
        self._encoding = encoding
        self._connect_timeout_s = connect_timeout_s
        self._recv_timeout_s = recv_timeout_s
        self._sock: socket.socket | None = None
        self._latest: "queue.Queue[FrameEnvelope]" = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._recv_thread: threading.Thread | None = None

    def start(self) -> None:
        self._sock = socket.create_connection(
            (self._host, self._port),
            timeout=self._connect_timeout_s,
        )
        self._sock.settimeout(self._recv_timeout_s)
        self._stop_event.clear()
        self._recv_thread = threading.Thread(
            target=self._recv_loop,
            name=f"vision-tcp-{self._host}:{self._port}",
            daemon=True,
        )
        self._recv_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:  # noqa: BLE001
                pass
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._sock = None
        thread = self._recv_thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._recv_thread = None

    def next_frame(self, timeout: float | None = 1.0) -> FrameEnvelope | None:
        try:
            return self._latest.get(timeout=timeout)
        except queue.Empty:
            return None

    # ── recv loop ────────────────────────────────────────────────

    def _recv_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                payload = self._recv_one_frame()
            except socket.timeout:
                continue
            except OSError:
                # Socket closed mid-recv — exit cleanly.
                return
            if payload is None:
                return  # connection closed
            envelope = FrameEnvelope(
                width=0, height=0,  # producer-supplied dimensions
                                    # aren't on the wire envelope by
                                    # design (see class docstring)
                encoding=self._encoding,
                data=payload,
            )
            # Latest-frame-wins (same as USB).
            try:
                self._latest.get_nowait()
            except queue.Empty:
                pass
            try:
                self._latest.put_nowait(envelope)
            except queue.Full:
                pass

    def _recv_one_frame(self) -> bytes | None:
        header = self._recv_exact(4)
        if header is None:
            return None
        (length,) = struct.unpack("!I", header)
        if length == 0 or length > 64 * 1024 * 1024:
            # 64 MB cap — anything larger is wire corruption,
            # not a real frame.
            raise OSError(
                f"TCPCameraAdapter: implausible frame length {length}"
            )
        return self._recv_exact(length)

    def _recv_exact(self, n: int) -> bytes | None:
        sock = self._sock
        assert sock is not None
        out = bytearray()
        while len(out) < n:
            chunk = sock.recv(n - len(out))
            if not chunk:
                return None  # peer closed cleanly
            out.extend(chunk)
        return bytes(out)
