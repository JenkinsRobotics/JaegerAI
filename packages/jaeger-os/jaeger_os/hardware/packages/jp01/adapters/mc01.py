"""MC01 — ESP32 motion controller adapter.

Implements the generic ``MotorAdapter`` Protocol (so the stock
``MotorNode`` drives it from ``/act/motion``) plus the JP01 verbs the
``motion(action=…)`` capability handlers call directly.

Firmware truth (survey 2026-06-12):
  * ``MJ[a1,a2,speed]`` — servos; firmware clamps a1 to 40-150°,
    a2 to 70-105°, speed is percent (CC01's default preview is 10).
  * ``MM[s1,s2,dur]`` — drive motors; firmware clamps dur ≤ 2 s and
    auto-neutralizes on expiry (the embryo of the L0 watchdog).
  * ``MM[0,0,0]`` — stop ("Emergency Stop Executed" in DockyMotor.h).
    It rides the ordinary command path — there is NO hard-bounded
    firmware e-stop yet, which is why live motors stay beta-gated.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from jaeger_os.hardware.link import Link
from jaeger_os.hardware.protocol import WireEvent

JOINT1_RANGE = (40, 150)
JOINT2_RANGE = (70, 105)
MAX_DRIVE_DURATION_S = 2.0


class Mc01MotorAdapter:
    """Stateless driver over one Link (daemon brief Rule 2 — the
    only state held is the link handle + last-heartbeat cache)."""

    def __init__(self, *, max_speed_mps: float = 0.5) -> None:
        # Placeholder calibration: 1.0 → full forward maps to 100 %
        # motor. Real value measured when live hardware walks.
        self.max_speed_mps = float(max_speed_mps)
        self._link: Link | None = None
        self._lock = threading.Lock()
        self._last_heartbeat: str = ""
        self._last_heartbeat_ts: float | None = None
        self._lines_seen = 0

    # ── wiring (boot calls these) ─────────────────────────────────

    def attach_link(self, link: Link) -> None:
        self._link = link

    def on_wire_event(self, event: WireEvent) -> None:
        self._lines_seen += 1
        if event.kind == "telemetry":
            self._last_heartbeat = event.text
            self._last_heartbeat_ts = time.monotonic()

    # ── MotorAdapter Protocol (generic MotorNode) ─────────────────

    def start(self) -> None:
        link = self._require_link()
        if not link.connected:
            link.open()
        link.send("CN")           # firmware handshake

    def stop(self) -> None:
        """Safe shutdown: neutralize motors, release the board."""
        link = self._link
        if link is None or not link.connected:
            return
        try:
            link.send("MM[0,0,0]")
            link.send("DC")
        except Exception:  # noqa: BLE001 — teardown never raises
            pass
        link.close()

    def send_velocity(
        self,
        *,
        linear_x_mps: float,
        linear_y_mps: float,   # noqa: ARG002 — diff-drive: no lateral axis
        angular_z_rps: float,
        duration_s: float,
    ) -> None:
        """Twist → differential ``MM[s1,s2,dur]``. Lateral velocity is
        ignored (two wheels)."""
        scale = 100.0 / self.max_speed_mps if self.max_speed_mps else 0.0
        forward = linear_x_mps * scale
        turn = angular_z_rps * 50.0      # placeholder turn authority
        s1 = _clamp(round(forward + turn), -100, 100)
        s2 = _clamp(round(forward - turn), -100, 100)
        self.drive(s1=s1, s2=s2, duration_s=duration_s)

    def send_waypoint(self, *, target_xy: list[float]) -> None:
        raise NotImplementedError(
            "JP01-MC01 has no x/y waypoint controller (no IMU, no "
            "odometry) — use motion(action='move_joints') or velocity"
        )

    # ── JP01 verbs (capability handlers) ──────────────────────────

    def move_joints(self, *, a1: int, a2: int, speed: int = 10) -> str:
        cmd = f"MJ[{int(a1)},{int(a2)},{int(speed)}]"
        self._send(cmd)
        return cmd

    def drive(self, *, s1: int, s2: int, duration_s: float) -> str:
        dur = min(float(duration_s), MAX_DRIVE_DURATION_S)
        # Firmware takes whole seconds (CC01 sends ints); keep that.
        cmd = f"MM[{int(s1)},{int(s2)},{int(round(dur))}]"
        self._send(cmd)
        return cmd

    def estop(self) -> None:
        """L1 node-local stop — immediate write on the open transport,
        bypassing everything above it. Called by the EStopLatch."""
        link = self._link
        if link is not None and link.connected:
            link.send("MM[0,0,0]")

    def telemetry(self) -> dict[str, Any]:
        age = (
            round(time.monotonic() - self._last_heartbeat_ts, 1)
            if self._last_heartbeat_ts is not None else None
        )
        return {
            "controller": "mc01",
            "last_heartbeat": self._last_heartbeat,
            "heartbeat_age_s": age,
            "lines_seen": self._lines_seen,
            "link": (self._link.health() if self._link else {}),
        }

    # ── internals ─────────────────────────────────────────────────

    def _require_link(self) -> Link:
        if self._link is None:
            raise ConnectionError("mc01 adapter has no link attached")
        return self._link

    def _send(self, cmd: str) -> None:
        with self._lock:
            self._require_link().send(cmd)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def simulator() -> Callable[[bytes], bytes | None]:
    """Firmware-shaped responder for ``simulated: true``. Mirrors the
    reply style of JP01-MC01.ino: handshake string on CN, ack lines
    for commands, a status block on GT."""

    def respond(data: bytes) -> bytes | None:
        line = data.decode("utf-8", "replace").strip()
        head = line.split("[", 1)[0]
        if head == "CN":
            return b"JP01-MC01 Connected\n"
        if head == "DC":
            return b"JP01-MC01 Disconnected\n"
        if head == "GT":
            return (
                b"--- STATUS UPDATE --- sim mc01 servos=90,90 "
                b"motors=0,0\n"
            )
        if line == "MM[0,0,0]":
            return b"Emergency Stop Executed\n"
        if head in ("MJ", "MM"):
            return f"ACK {line}\n".encode()
        return f"ERR unknown command: {line}\n".encode()

    return respond


__all__ = [
    "Mc01MotorAdapter", "simulator",
    "JOINT1_RANGE", "JOINT2_RANGE", "MAX_DRIVE_DURATION_S",
]
