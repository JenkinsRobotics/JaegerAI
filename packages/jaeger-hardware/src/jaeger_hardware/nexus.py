"""NexusUI hardware telemetry & safe-gated station bridge.

Connects JaegerAI to standalone NexusUI hardware HMI stations (``/api/info``,
``/api/layouts``, and the ``/ws`` hello/control/write/cmd protocol) using pure
Python stdlib, while strictly respecting:
  - JaegerAI's fail-closed L2 ``EStopLatch``
  - NexusUI's single-operator ``claim`` / ``release`` control lock
  - Zero interlock overrides by autonomous agents (human operators only)
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
import hashlib
import ipaddress
import json
import os
import socket
import ssl
import struct
import time
from typing import Any, Mapping
import urllib.error
import urllib.parse
import urllib.request

from .safety import EStopLatch


_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_DEFAULT_STATION_URL = "http://127.0.0.1:8000"


def _validate_station_url(base_url: str, *, allow_remote: bool = False) -> urllib.parse.SplitResult:
    raw = (base_url or _DEFAULT_STATION_URL).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"unsupported NexusUI URL scheme: {parsed.scheme!r}")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("NexusUI station URL requires a hostname")
    if host in ("localhost", "127.0.0.1", "::1"):
        return parsed
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not allow_remote:
            raise PermissionError(
                f"remote NexusUI host {host!r} blocked by default; pass allow_remote=True to allow non-local hosts"
            )
        return parsed
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise PermissionError(f"unsafe NexusUI host IP blocked: {host}")
    if not (ip.is_loopback or ip.is_private) and not allow_remote:
        raise PermissionError(
            f"public NexusUI host {host} blocked by default; pass allow_remote=True for remote stations"
        )
    return parsed


class _StdlibWSClient:
    """Minimal RFC 6455 JSON WebSocket client over stdlib sockets (no external deps)."""

    def __init__(self, parsed_http: urllib.parse.SplitResult, path_with_query: str, *, timeout_s: float = 4.0) -> None:
        self._parsed = parsed_http
        self._path = path_with_query
        self._timeout = max(0.5, float(timeout_s))
        self._sock: socket.socket | None = None
        self._buf = bytearray()

    def __enter__(self) -> "_StdlibWSClient":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def connect(self) -> None:
        host = self._parsed.hostname or "127.0.0.1"
        use_tls = self._parsed.scheme == "https"
        port = self._parsed.port or (443 if use_tls else 80)
        raw_sock = socket.create_connection((host, port), timeout=self._timeout)
        if use_tls:
            ctx = ssl.create_default_context()
            raw_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
        raw_sock.settimeout(self._timeout)
        self._sock = raw_sock

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        host_hdr = f"{host}:{port}" if self._parsed.port else host
        req = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {host_hdr}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        raw_sock.sendall(req)

        header_bytes = self._read_until(b"\r\n\r\n", max_bytes=16384)
        header_text = header_bytes.decode("iso-8859-1", errors="replace")
        lines = header_text.split("\r\n")
        if not lines or "101" not in lines[0]:
            raise ConnectionError(f"WebSocket upgrade rejected: {lines[0] if lines else 'empty'}")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        if headers.get("sec-websocket-accept") != expected_accept:
            raise ConnectionError("WebSocket Sec-WebSocket-Accept mismatch")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._send_frame(0x8, b"")
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send_json(self, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, body)

    def recv_json(self) -> dict[str, Any]:
        while True:
            opcode, data = self._recv_frame()
            if opcode == 0x1:
                parsed = json.loads(data.decode("utf-8"))
                if isinstance(parsed, dict):
                    return parsed
                return {"raw": parsed}
            if opcode == 0x9:  # ping -> pong
                self._send_frame(0xA, data)
            elif opcode == 0x8:  # close
                raise ConnectionError("WebSocket closed by station")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._sock is None:
            raise ConnectionError("WebSocket not connected")
        mask = os.urandom(4)
        length = len(payload)
        header = bytearray([0x80 | (opcode & 0x0F)])
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        b1, b2 = self._read_exact(2)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask_key = self._read_exact(4) if masked else b""
        data = self._read_exact(length)
        if masked:
            data = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
        return opcode, data

    def _read_exact(self, n: int) -> bytes:
        assert self._sock is not None
        while len(self._buf) < n:
            chunk = self._sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("unexpected EOF on WebSocket")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _read_until(self, marker: bytes, *, max_bytes: int) -> bytes:
        assert self._sock is not None
        while True:
            idx = self._buf.find(marker)
            if idx != -1:
                end = idx + len(marker)
                out = bytes(self._buf[:end])
                del self._buf[:end]
                return out
            if len(self._buf) >= max_bytes:
                raise ConnectionError("WebSocket handshake header exceeded max size")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("unexpected EOF during WebSocket handshake")
            self._buf.extend(chunk)


@dataclass(slots=True)
class NexusStationSnapshot:
    """Normalized point-in-time snapshot of a live NexusUI hardware station."""

    station_url: str
    engine_name: str
    control_mode: str
    controller: str | None
    override_active: bool
    channels: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    commands: list[dict[str, Any]] = field(default_factory=list)
    devices: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    locks: dict[str, str] = field(default_factory=dict)
    stations: list[dict[str, Any]] = field(default_factory=list)
    captured_at: float = field(default_factory=time.time)

    def active_alerts(self) -> list[dict[str, Any]]:
        return [a for a in self.alerts if a.get("active", True)]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["active_alert_count"] = len(self.active_alerts())
        data["channel_count"] = len(self.channels)
        data["device_count"] = len(self.devices)
        return data


def build_jp01_telemetry_channels(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a ``JP01Embodiment.observe()`` snapshot into NexusUI-compatible channels & values."""
    pose = observation.get("pose") if isinstance(observation.get("pose"), Mapping) else {}
    estop = observation.get("estop") if isinstance(observation.get("estop"), Mapping) else {}
    engaged = bool(estop.get("engaged", False))
    estop_reason = str(estop.get("reason") or "")
    channels = [
        {
            "name": "jp01.pan_deg",
            "kind": "number",
            "label": "Head Pan",
            "unit": "deg",
            "group": "jp01",
            "min": 30,
            "max": 150,
            "writable": True,
        },
        {
            "name": "jp01.tilt_deg",
            "kind": "number",
            "label": "Head Tilt",
            "unit": "deg",
            "group": "jp01",
            "min": 45,
            "max": 135,
            "writable": True,
        },
        {
            "name": "jp01.speed",
            "kind": "number",
            "label": "Motion Speed",
            "unit": "%",
            "group": "jp01",
            "min": 5,
            "max": 100,
            "writable": True,
        },
        {
            "name": "jp01.face_mood",
            "kind": "enum",
            "label": "Face Mood",
            "group": "jp01",
            "options": ["calm", "warm", "focused", "curious", "alert", "sleep"],
            "writable": True,
        },
        {
            "name": "jp01.estop_engaged",
            "kind": "bool",
            "label": "L2 E-Stop Latched",
            "group": "safety",
            "writable": False,
        },
        {
            "name": "jp01.dry_run",
            "kind": "bool",
            "label": "Dry Run Mode",
            "group": "safety",
            "writable": False,
        },
        {
            "name": "jp01.tx_count",
            "kind": "number",
            "label": "Frames Sent",
            "group": "telemetry",
            "fmt": "int",
            "writable": False,
        },
    ]
    values = {
        "jp01.pan_deg": float(pose.get("pan_deg", 90)),
        "jp01.tilt_deg": float(pose.get("tilt_deg", 90)),
        "jp01.speed": float(pose.get("speed", 40)),
        "jp01.face_mood": str(observation.get("face_mood") or "calm"),
        "jp01.estop_engaged": engaged,
        "jp01.dry_run": bool(observation.get("dry_run", True)),
        "jp01.tx_count": int(observation.get("tx_count", 0)),
    }
    locks = {}
    if engaged:
        reason = estop_reason or "operator E-Stop"
        for ch in ("jp01.pan_deg", "jp01.tilt_deg", "jp01.speed"):
            locks[ch] = f"E-Stop latched: {reason}"
    return {
        "engine": {"name": str(observation.get("embodiment") or "jp01_droid"), "control": "lock"},
        "channels": channels,
        "values": values,
        "locks": locks,
        "alerts": (
            [{"id": "jp01_estop", "message": f"JP01 E-Stop latched ({estop_reason or 'operator'})", "level": "alarm", "active": True}]
            if engaged
            else []
        ),
    }


class NexusStationBridge:
    """Safe, read-first bridge to a live NexusUI hardware workbench station."""

    def __init__(
        self,
        base_url: str = _DEFAULT_STATION_URL,
        *,
        station_name: str = "JaegerAI",
        estop_latch: EStopLatch | None = None,
        read_only: bool = True,
        allow_remote: bool = False,
        timeout_s: float = 4.0,
    ) -> None:
        self._parsed = _validate_station_url(base_url, allow_remote=allow_remote)
        self.base_url = f"{self._parsed.scheme}://{self._parsed.netloc}"
        self.station_name = (station_name or "JaegerAI")[:40].strip() or "JaegerAI"
        self.estop_latch = estop_latch
        self.read_only = bool(read_only)
        self.timeout_s = max(0.5, float(timeout_s))

    def _http_get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "JaegerAI-NexusBridge/1.0"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"data": data}

    def get_info(self) -> dict[str, Any]:
        """Fetch lightweight ``/api/info`` metadata from the NexusUI station."""
        info = self._http_get_json("/api/info")
        return {"ok": True, "station_url": self.base_url, **info}

    def list_layouts(self) -> dict[str, Any]:
        """List saved NexusUI layouts from ``/api/layouts``."""
        data = self._http_get_json("/api/layouts")
        return {"ok": True, "station_url": self.base_url, **data}

    def snapshot(self) -> NexusStationSnapshot:
        """Connect briefly to ``/ws`` and capture the live station ``hello`` snapshot."""
        qs = urllib.parse.urlencode({"name": self.station_name})
        with _StdlibWSClient(self._parsed, f"/ws?{qs}", timeout_s=self.timeout_s) as ws:
            hello = self._wait_for_type(ws, "hello")
        eng = hello.get("engine") if isinstance(hello.get("engine"), Mapping) else {}
        ctrl = hello.get("control") if isinstance(hello.get("control"), Mapping) else {}
        return NexusStationSnapshot(
            station_url=self.base_url,
            engine_name=str(eng.get("name") or "unknown"),
            control_mode=str(ctrl.get("mode") or eng.get("control") or "lock"),
            controller=ctrl.get("holder_name"),
            override_active=bool(ctrl.get("override", False)),
            channels=list(hello.get("channels") or []),
            values=dict(hello.get("values") or {}),
            commands=list(hello.get("commands") or []),
            devices=list(hello.get("devices") or []),
            alerts=list(hello.get("alerts") or []),
            locks=dict(hello.get("locks") or {}),
            stations=list(hello.get("stations") or []),
        )

    def write_channel(
        self,
        channel: str,
        value: Any,
        *,
        allow_write: bool = False,
        force_claim: bool = False,
    ) -> dict[str, Any]:
        """Write a value to a writable NexusUI channel while honoring E-Stop & single-operator lock."""
        refusal = self._guard_write(allow_write=allow_write)
        if refusal is not None:
            return refusal
        if not channel or not str(channel).strip():
            return {"ok": False, "error": "channel name is required"}
        return self._execute_controlled_op(
            {"t": "write", "ch": str(channel).strip(), "v": value, "id": "jaeger-write-1"},
            force_claim=force_claim,
        )

    def run_command(
        self,
        name: str,
        args: Mapping[str, Any] | None = None,
        *,
        allow_write: bool = False,
        force_claim: bool = False,
    ) -> dict[str, Any]:
        """Invoke a declared NexusUI command while honoring E-Stop & single-operator lock."""
        refusal = self._guard_write(allow_write=allow_write)
        if refusal is not None:
            return refusal
        if not name or not str(name).strip():
            return {"ok": False, "error": "command name is required"}
        return self._execute_controlled_op(
            {"t": "cmd", "name": str(name).strip(), "args": dict(args or {}), "id": "jaeger-cmd-1"},
            force_claim=force_claim,
        )

    def _guard_write(self, *, allow_write: bool) -> dict[str, Any] | None:
        if self.estop_latch is not None and self.estop_latch.engaged:
            return {"ok": False, "error": self.estop_latch.refusal()}
        if self.read_only and not allow_write:
            return {
                "ok": False,
                "error": "NexusStationBridge is read-only; explicit owner approval (allow_write=True) is required",
            }
        return None

    def _execute_controlled_op(self, op_msg: Mapping[str, Any], *, force_claim: bool) -> dict[str, Any]:
        qs = urllib.parse.urlencode({"name": self.station_name})
        claimed = False
        with _StdlibWSClient(self._parsed, f"/ws?{qs}", timeout_s=self.timeout_s) as ws:
            hello = self._wait_for_type(ws, "hello")
            ctrl = hello.get("control") if isinstance(hello.get("control"), Mapping) else {}
            control_mode = str(ctrl.get("mode") or "lock")
            try:
                if control_mode == "lock":
                    ws.send_json({"t": "claim", "force": bool(force_claim), "id": "jaeger-claim"})
                    claim_ack = self._wait_for_ack(ws, "jaeger-claim")
                    if not claim_ack.get("ok"):
                        return {
                            "ok": False,
                            "error": str(claim_ack.get("error") or "station control lock held by another operator"),
                            "control_holder": ctrl.get("holder_name"),
                        }
                    claimed = True
                ws.send_json(op_msg)
                ack = self._wait_for_ack(ws, str(op_msg.get("id") or ""))
                return {
                    "ok": bool(ack.get("ok")),
                    "error": ack.get("error"),
                    "station_url": self.base_url,
                    "operation": op_msg.get("t"),
                    "target": op_msg.get("ch") or op_msg.get("name"),
                }
            finally:
                if claimed:
                    try:
                        ws.send_json({"t": "release", "id": "jaeger-release"})
                        self._wait_for_ack(ws, "jaeger-release")
                    except Exception:  # noqa: BLE001
                        pass

    @staticmethod
    def _wait_for_type(ws: _StdlibWSClient, expected_type: str, max_msgs: int = 30) -> dict[str, Any]:
        for _ in range(max_msgs):
            msg = ws.recv_json()
            if msg.get("t") == expected_type:
                return msg
        raise TimeoutError(f"did not receive NexusUI message type {expected_type!r}")

    @staticmethod
    def _wait_for_ack(ws: _StdlibWSClient, req_id: str, max_msgs: int = 40) -> dict[str, Any]:
        for _ in range(max_msgs):
            msg = ws.recv_json()
            if msg.get("t") == "ack" and (not req_id or msg.get("id") == req_id):
                return msg
        raise TimeoutError(f"did not receive NexusUI ack for {req_id!r}")


__all__ = [
    "NexusStationBridge",
    "NexusStationSnapshot",
    "build_jp01_telemetry_channels",
]
