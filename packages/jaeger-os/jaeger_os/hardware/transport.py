"""Byte-channel transports — the wire half of a hardware link.

The verbs deliberately mirror ``JP01-CC01/plugins/Core/serial_handler.py``
(connect / disconnect / is_connected / write / read) — the proven shape
from the robot that's been driving real boards. A Transport carries
BYTES for command/response links; high-rate streams (video frames,
telemetry PUB feeds) do NOT ride this ABC — they go straight onto the
JROS bus via the owning node's subscriber thread (the vision node's
``FrameEnvelope`` path is the precedent).
"""

from __future__ import annotations

import abc
import threading
import time
from typing import Any, Callable


class Transport(abc.ABC):
    """One byte channel to one controller. Implementations must be
    safe to ``open()``/``close()`` repeatedly (idempotent close)."""

    @abc.abstractmethod
    def open(self) -> None:
        """Open the channel. Raises on failure — the Link decides
        whether to fall back to a relay."""

    @abc.abstractmethod
    def close(self) -> None:
        """Close the channel. Idempotent; never raises."""

    @abc.abstractmethod
    def is_open(self) -> bool: ...

    @abc.abstractmethod
    def write_bytes(self, data: bytes) -> None:
        """Write one encoded frame. Raises on a dead channel."""

    @abc.abstractmethod
    def read_bytes(self, timeout_s: float = 0.1) -> bytes | None:
        """Return raw inbound bytes (any amount — framing is the
        Protocol's job) or None when nothing arrived in time."""

    @abc.abstractmethod
    def descriptor(self) -> str:
        """One-line label for logs/health ('serial /dev/… @115200')."""


class SerialTransport(Transport):
    """pyserial line channel. Lazy import — the framework must load on
    hosts without pyserial (CI, simulation-only dev)."""

    def __init__(self, *, port: str, baud: int = 115200,
                 timeout_s: float = 0.1) -> None:
        self.port = port
        self.baud = int(baud)
        self.timeout_s = float(timeout_s)
        self._serial: Any = None

    def open(self) -> None:
        import serial  # lazy — optional dependency
        self._serial = serial.Serial(
            self.port, self.baud, timeout=self.timeout_s,
        )

    def close(self) -> None:
        s, self._serial = self._serial, None
        if s is not None:
            try:
                s.close()
            except Exception:  # noqa: BLE001 — close never raises
                pass

    def is_open(self) -> bool:
        return self._serial is not None and bool(
            getattr(self._serial, "is_open", False)
        )

    def write_bytes(self, data: bytes) -> None:
        if self._serial is None:
            raise ConnectionError(f"serial {self.port} not open")
        self._serial.write(data)

    def read_bytes(self, timeout_s: float = 0.1) -> bytes | None:
        if self._serial is None:
            return None
        try:
            if self._serial.in_waiting:
                return self._serial.readline()
        except Exception:  # noqa: BLE001 — surfaced via link health, not raise
            return None
        return None

    def descriptor(self) -> str:
        return f"serial {self.port} @{self.baud}"


class ZmqReqTransport(Transport):
    """ZMQ REQ command channel (the VCC01 :5556/:5560 shape — and the
    CC01 relay path, where MC01/AVC01 bracket commands ride a REQ to
    the Jetson which owns the actual serial port).

    ``target`` is the relay routing key: JP01's relay protocol wraps a
    command as ``{"target": "motion", "cmd": "MJ[…]"}`` (mirroring
    ``zmq_client.send_command(target, cmd_str)`` in
    ``JP01-CC01/comms/zmq_client.py``). Empty target sends the raw
    payload unwrapped.
    """

    def __init__(self, *, endpoint: str, target: str = "",
                 timeout_s: float = 2.0) -> None:
        self.endpoint = endpoint
        self.target = target
        self.timeout_s = float(timeout_s)
        self._ctx: Any = None
        self._sock: Any = None
        self._rx: list[bytes] = []
        self._lock = threading.Lock()

    def open(self) -> None:
        import zmq  # lazy
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.REQ)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.RCVTIMEO, int(self.timeout_s * 1000))
        self._sock.setsockopt(zmq.SNDTIMEO, int(self.timeout_s * 1000))
        self._sock.connect(self.endpoint)

    def close(self) -> None:
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close(0)
            except Exception:  # noqa: BLE001
                pass

    def is_open(self) -> bool:
        return self._sock is not None

    def write_bytes(self, data: bytes) -> None:
        if self._sock is None:
            raise ConnectionError(f"zmq {self.endpoint} not open")
        if self.target:
            import json
            payload = json.dumps(
                {"target": self.target, "cmd": data.decode("utf-8", "replace").strip()}
            ).encode()
        else:
            payload = data
        with self._lock:
            self._sock.send(payload)
            try:
                reply = self._sock.recv()
                self._rx.append(reply)
            except Exception as exc:  # noqa: BLE001 — REQ must recv before next send
                # A REQ socket that missed its reply is wedged; reopen.
                self.close()
                self.open()
                raise ConnectionError(
                    f"zmq {self.endpoint} reply timeout"
                ) from exc

    def read_bytes(self, timeout_s: float = 0.1) -> bytes | None:  # noqa: ARG002
        with self._lock:
            return self._rx.pop(0) if self._rx else None

    def descriptor(self) -> str:
        suffix = f" target={self.target}" if self.target else ""
        return f"zmq-req {self.endpoint}{suffix}"


class MockTransport(Transport):
    """Simulation / test transport. Records every write; replies come
    from a ``responder`` callable (bytes → bytes | None) or queue up
    via :meth:`inject`. This is the ``simulated: true`` backend and
    the seam every headless test drives."""

    def __init__(
        self,
        *,
        responder: Callable[[bytes], bytes | None] | None = None,
        name: str = "mock",
    ) -> None:
        self.name = name
        self.responder = responder
        self.writes: list[bytes] = []
        self._inbox: list[bytes] = []
        self._open = False
        self.opened_at: float | None = None

    def open(self) -> None:
        self._open = True
        self.opened_at = time.time()

    def close(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def write_bytes(self, data: bytes) -> None:
        if not self._open:
            raise ConnectionError("mock transport not open")
        self.writes.append(data)
        if self.responder is not None:
            reply = self.responder(data)
            if reply:
                self._inbox.append(reply)

    def read_bytes(self, timeout_s: float = 0.1) -> bytes | None:  # noqa: ARG002
        return self._inbox.pop(0) if self._inbox else None

    def inject(self, data: bytes) -> None:
        """Simulate unsolicited inbound traffic (heartbeats)."""
        self._inbox.append(data)

    def descriptor(self) -> str:
        return f"mock {self.name}"


__all__ = [
    "Transport", "SerialTransport", "ZmqReqTransport", "MockTransport",
]
