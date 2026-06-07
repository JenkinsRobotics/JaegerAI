"""adapters.py — motor adapters.

Generic universal adapter Protocol + one concrete reference
implementation (``SerialMotorAdapter``) for boards that speak a
simple ASCII line protocol.  Per-instance subclasses customise
the wire format when JP01-MC01 (or any other specific board)
wires up.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol


class MotorAdapter(Protocol):
    """The interface the motor node depends on.

    Production: instance-specific subclass of
    :class:`SerialMotorAdapter` OR a TCP variant.  Tests: a mock
    that records calls.
    """

    def start(self) -> None:
        """Open the link to the motor controller."""
        ...

    def stop(self) -> None:
        """Close the link.  Idempotent."""
        ...

    def send_velocity(
        self,
        *,
        linear_x_mps: float,
        linear_y_mps: float,
        angular_z_rps: float,
        duration_s: float,
    ) -> None:
        """Command a velocity twist held for ``duration_s`` seconds."""
        ...

    def send_waypoint(
        self,
        *,
        target_xy: list[float],
    ) -> None:
        """Command a waypoint goal in metres (frame TBD by adapter)."""
        ...


class SerialMotorAdapter:
    """Reference adapter for a board that speaks ASCII commands over
    USB-CDC or TCP.  Subclass and override the ``_format_*`` methods
    to match your board's wire format.

    Default protocol (universal, no JP01 specifics):
        VEL <linear_x> <linear_y> <angular_z> <duration_s>\\n
        WP  <x> <y>\\n
        STOP\\n

    Real instance-level adapters (JP01-MC01 ESP32 over Wi-Fi /
    USB) subclass and override these strings.
    """

    def __init__(
        self,
        *,
        write_line=None,
    ) -> None:
        """``write_line`` is a callable that takes a bytes line and
        writes it to the wire.  Concrete subclasses provide a
        serial.Serial or socket variant; tests inject a recorder.
        Default: no-op (safe for tests that just check formatting)."""
        self._write_line = write_line or (lambda b: None)
        self._lock = threading.Lock()
        self._started = False

    # ── lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        # Safety: stop motion on close so a crashed node doesn't
        # leave the robot rolling.
        try:
            self._write(self._format_stop())
        except Exception:  # noqa: BLE001
            pass
        self._started = False

    # ── commands ──────────────────────────────────────────────────

    def send_velocity(
        self,
        *,
        linear_x_mps: float,
        linear_y_mps: float,
        angular_z_rps: float,
        duration_s: float,
    ) -> None:
        self._write(self._format_velocity(
            linear_x_mps=linear_x_mps,
            linear_y_mps=linear_y_mps,
            angular_z_rps=angular_z_rps,
            duration_s=duration_s,
        ))

    def send_waypoint(self, *, target_xy: list[float]) -> None:
        if len(target_xy) != 2:
            raise ValueError(
                f"send_waypoint: target_xy must be [x, y]; got {target_xy!r}"
            )
        self._write(self._format_waypoint(x=target_xy[0], y=target_xy[1]))

    # ── overridable wire format ───────────────────────────────────

    def _format_velocity(
        self, *, linear_x_mps, linear_y_mps, angular_z_rps, duration_s,
    ) -> bytes:
        return (
            f"VEL {linear_x_mps:.4f} {linear_y_mps:.4f} "
            f"{angular_z_rps:.4f} {duration_s:.4f}\n"
        ).encode("ascii")

    def _format_waypoint(self, *, x, y) -> bytes:
        return f"WP {x:.4f} {y:.4f}\n".encode("ascii")

    def _format_stop(self) -> bytes:
        return b"STOP\n"

    # ── thread-safe write ────────────────────────────────────────

    def _write(self, line: bytes) -> None:
        with self._lock:
            self._write_line(line)
