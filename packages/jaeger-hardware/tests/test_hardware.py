"""Tests for standalone jaeger-hardware package (JP01 protocol, E-Stop latch & NexusUI bridge)."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from typing import Any

import pytest

from jaeger_contracts import EmbodimentPort
from jaeger_hardware import (
    AsciiBracketProtocol,
    EStopLatch,
    JP01Embodiment,
    NexusStationBridge,
    build_jp01_telemetry_channels,
)


def test_jp01_protocol_clamping_and_estop_latch() -> None:
    proto = AsciiBracketProtocol()
    assert proto.encode({"header": "MJ", "args": [90, 100, 10]}) == b"MJ[90,100,10]\n"
    evs = proto.feed(b"STATUS UPDATE temp=38C\nOK\n")
    assert evs[0].kind == "telemetry" and evs[1].kind == "line"

    latch = EStopLatch()
    bot = JP01Embodiment(estop_latch=latch, dry_run=True)
    assert isinstance(bot, EmbodimentPort)

    # Out-of-range pan is clamped safely to [30, 150]
    res = bot.act("head_move", {"pan_deg": 999, "tilt_deg": 95, "speed": 50})
    assert res["ok"] is True and res["pose"]["pan_deg"] == 150 and res["frame"] == "MJ[150,95,50]"

    # E-Stop refuses motion and refuses non-operator release!
    bot.estop("human_too_close")
    refused = bot.act("head_move", {"pan_deg": 90})
    assert refused["ok"] is False and "e-stop latched" in refused["error"]
    with pytest.raises(PermissionError):
        latch.release(source="agent")
    latch.release(source="operator")
    assert bot.act("face_expression", {"mood": "warm"})["ok"] is True


def test_jp01_telemetry_channels_export_for_nexusui() -> None:
    latch = EStopLatch()
    bot = JP01Embodiment(estop_latch=latch, dry_run=True)
    bot.act("head_move", {"pan_deg": 110, "tilt_deg": 80, "speed": 55})

    export = build_jp01_telemetry_channels(bot.observe())
    assert export["engine"]["name"] == "jp01_droid"
    assert export["values"]["jp01.pan_deg"] == 110.0
    assert export["values"]["jp01.estop_engaged"] is False
    assert export["locks"] == {}
    assert export["alerts"] == []

    bot.estop("bench_test")
    latched_export = build_jp01_telemetry_channels(bot.observe())
    assert latched_export["values"]["jp01.estop_engaged"] is True
    assert "jp01.pan_deg" in latched_export["locks"]
    assert len(latched_export["alerts"]) == 1


class _MockNexusServer:
    """Tiny loopback HTTP + RFC 6455 WebSocket mock matching NexusUI gateway.py."""

    def __init__(self, *, lock_holder: str | None = None) -> None:
        self.lock_holder = lock_holder
        self.received_ops: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "_MockNexusServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._sock.close()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    @staticmethod
    def _send_ws_text(conn: socket.socket, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        length = len(raw)
        if length < 126:
            hdr = bytes([0x81, length])
        else:
            hdr = bytes([0x81, 126]) + struct.pack("!H", length)
        conn.sendall(hdr + raw)

    @staticmethod
    def _recv_exact(conn: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf.extend(chunk)
        return bytes(buf)

    def _recv_ws_json(self, conn: socket.socket) -> dict[str, Any] | None:
        b1, b2 = self._recv_exact(conn, 2)
        opcode = b1 & 0x0F
        if opcode == 0x8:
            return None
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(conn, 2))[0]
        mask = self._recv_exact(conn, 4) if masked else b""
        data = self._recv_exact(conn, length)
        if masked:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        return json.loads(data.decode("utf-8"))

    def _handle_conn(self, conn: socket.socket) -> None:
        conn.settimeout(2.0)
        try:
            raw_req = b""
            while b"\r\n\r\n" not in raw_req:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                raw_req += chunk
            lines = raw_req.decode("iso-8859-1").split("\r\n")
            path = lines[0].split(" ")[1]
            headers = {
                line.split(":", 1)[0].strip().lower(): line.split(":", 1)[1].strip()
                for line in lines[1:]
                if ":" in line
            }
            if path.startswith("/api/info"):
                body = json.dumps({"name": "Bench Rover", "control": "lock", "stations": 1, "uptime": 42.0}).encode()
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )
                return
            if path.startswith("/api/layouts"):
                body = json.dumps({"layouts": [{"name": "default", "title": "Main"}], "default": "default"}).encode()
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode()
                    + b"\r\n\r\n"
                    + body
                )
                return
            if path.startswith("/ws"):
                ws_key = headers["sec-websocket-key"]
                accept = base64.b64encode(
                    hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
                conn.sendall(
                    (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                    ).encode()
                )
                self._send_ws_text(
                    conn,
                    {
                        "t": "hello",
                        "engine": {"name": "Bench Rover", "control": "lock"},
                        "control": {
                            "mode": "lock",
                            "holder_name": self.lock_holder,
                            "override": False,
                        },
                        "channels": [{"name": "battery.v", "kind": "number", "unit": "V", "writable": False}],
                        "values": {"battery.v": 24.6, "drive.enable": False},
                        "commands": [{"name": "home_arm", "label": "Home Arm"}],
                        "devices": [{"id": "drive", "label": "Drive"}],
                        "alerts": [{"id": "a1", "message": "Temp warm", "active": True}],
                        "locks": {},
                        "stations": [{"id": "s1", "name": "JaegerAI"}],
                    },
                )
                while True:
                    msg = self._recv_ws_json(conn)
                    if msg is None:
                        break
                    self.received_ops.append(msg)
                    t = msg.get("t")
                    rid = msg.get("id")
                    if t == "claim":
                        if self.lock_holder and not msg.get("force"):
                            self._send_ws_text(
                                conn,
                                {"t": "ack", "id": rid, "ok": False, "error": f"{self.lock_holder} has control"},
                            )
                        else:
                            self._send_ws_text(conn, {"t": "ack", "id": rid, "ok": True})
                    else:
                        self._send_ws_text(conn, {"t": "ack", "id": rid, "ok": True})
        except Exception:  # noqa: BLE001
            pass
        finally:
            conn.close()


def test_nexus_station_bridge_snapshot_safety_and_polite_control() -> None:
    # Public remote host blocked by default (SSRF guard)
    with pytest.raises(PermissionError):
        NexusStationBridge("http://8.8.8.8:8000")

    latch = EStopLatch()
    with _MockNexusServer(lock_holder=None) as srv:
        bridge = NexusStationBridge(srv.url, estop_latch=latch, read_only=True)
        info = bridge.get_info()
        assert info["ok"] is True and info["name"] == "Bench Rover"
        layouts = bridge.list_layouts()
        assert layouts["ok"] is True and layouts["default"] == "default"

        snap = bridge.snapshot()
        assert snap.engine_name == "Bench Rover"
        assert snap.values["battery.v"] == 24.6
        assert len(snap.active_alerts()) == 1

        # Read-only blocks writes without explicit owner approval
        denied = bridge.write_channel("drive.enable", True)
        assert denied["ok"] is False and "read-only" in denied["error"]

        # E-Stop latch refuses even approved writes
        latch.engage("test_estop", source="operator")
        estop_denied = bridge.write_channel("drive.enable", True, allow_write=True)
        assert estop_denied["ok"] is False and "e-stop latched" in estop_denied["error"]
        latch.release(source="operator")

        # Approved write politely claims -> writes -> releases
        ok_write = bridge.write_channel("drive.enable", True, allow_write=True)
        assert ok_write["ok"] is True
        op_types = [op["t"] for op in srv.received_ops]
        assert op_types == ["claim", "write", "release"]
        assert srv.received_ops[0]["force"] is False

    # Respects existing human operator control lock without force-stealing
    with _MockNexusServer(lock_holder="Operator-Bench") as locked_srv:
        locked_bridge = NexusStationBridge(locked_srv.url, estop_latch=latch, read_only=False)
        blocked = locked_bridge.run_command("home_arm", allow_write=True)
        assert blocked["ok"] is False
        assert "Operator-Bench" in blocked["error"]
