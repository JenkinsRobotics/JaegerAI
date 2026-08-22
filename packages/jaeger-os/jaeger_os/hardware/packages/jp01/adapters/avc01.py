"""AVC01 — Teensy 4.1 audio/visual controller adapter.

Implements the generic ``LightAdapter`` Protocol (so the stock
``LightNode`` drives it from ``/act/light``) plus the JP01 verbs the
``lights(action=…)`` capability handlers call.

Firmware surface (survey 2026-06-12): ``CN``/``DC`` handshake,
``GT``/``ST`` status, NeoPixel ``MN[mode]`` + ``FN[wrgb-hex]``,
LED matrix ``MM[mode]`` + ``BM[brightness]`` + ``FM[rgb-hex]``,
30 s heartbeat status lines. (Note the header collision with MC01:
``MM`` here is *matrix mode* — different board, different wire.)
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from jaeger_os.hardware.link import Link
from jaeger_os.hardware.protocol import WireEvent

from ..devices import (
    build_matrix_brightness,
    build_matrix_frame,
    build_matrix_mode,
    build_neopixel_frame,
    build_neopixel_mode,
)

# Provisional generic-pattern → NeoPixel mode map for the stock
# LightNode path. Mode meanings re-checked against the .ino when the
# live walk happens; the capability path passes modes explicitly.
_PATTERN_TO_MODE = {"off": 0, "solid": 1, "pulse": 2, "rainbow": 3}


class Avc01LightAdapter:
    def __init__(self) -> None:
        self._link: Link | None = None
        self._lock = threading.Lock()
        self._last_heartbeat: str = ""
        self._last_heartbeat_ts: float | None = None
        self._lines_seen = 0

    # ── wiring ────────────────────────────────────────────────────

    def attach_link(self, link: Link) -> None:
        self._link = link

    def on_wire_event(self, event: WireEvent) -> None:
        self._lines_seen += 1
        if event.kind == "telemetry":
            self._last_heartbeat = event.text
            self._last_heartbeat_ts = time.monotonic()

    # ── LightAdapter Protocol (generic LightNode) ─────────────────

    def start(self) -> None:
        link = self._require_link()
        if not link.connected:
            link.open()
        link.send("CN")

    def stop(self) -> None:
        """Blank everything on shutdown (LightAdapter contract — no
        post-crash 'still glowing')."""
        link = self._link
        if link is None or not link.connected:
            return
        try:
            link.send(build_neopixel_mode(0))
            link.send(build_matrix_mode(0))
            link.send("DC")
        except Exception:  # noqa: BLE001 — teardown never raises
            pass
        link.close()

    def send_pattern(
        self,
        *,
        strip_id: str,   # noqa: ARG002 — one NeoPixel chain on JP01
        rgb: list[int],
        pattern: str,
        duration_ms: int,  # noqa: ARG002 — firmware modes self-time
    ) -> None:
        if pattern == "solid" and len(rgb) == 3:
            # Solid colour rides a single-frame FN (WRGB, W=0).
            self._send(build_neopixel_frame(
                f"00{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            ))
            return
        mode = _PATTERN_TO_MODE.get(pattern)
        if mode is None:
            raise ValueError(f"unknown pattern {pattern!r}")
        self._send(build_neopixel_mode(mode))

    # ── JP01 verbs (capability handlers) ──────────────────────────

    def set_mode(self, *, target: str, mode: int) -> str:
        cmd = (build_neopixel_mode(mode) if target == "neopixel"
               else build_matrix_mode(mode))
        self._send(cmd)
        return cmd

    def set_frame(self, *, target: str, frame_hex: str) -> str:
        cmd = (build_neopixel_frame(frame_hex) if target == "neopixel"
               else build_matrix_frame(frame_hex))
        self._send(cmd)
        return cmd

    def set_brightness(self, *, value: int) -> str:
        cmd = build_matrix_brightness(value)
        self._send(cmd)
        return cmd

    def request_status(self) -> None:
        self._send("ST")

    def telemetry(self) -> dict[str, Any]:
        age = (
            round(time.monotonic() - self._last_heartbeat_ts, 1)
            if self._last_heartbeat_ts is not None else None
        )
        return {
            "controller": "avc01",
            "last_heartbeat": self._last_heartbeat,
            "heartbeat_age_s": age,
            "lines_seen": self._lines_seen,
            "link": (self._link.health() if self._link else {}),
        }

    # ── internals ─────────────────────────────────────────────────

    def _require_link(self) -> Link:
        if self._link is None:
            raise ConnectionError("avc01 adapter has no link attached")
        return self._link

    def _send(self, cmd: str) -> None:
        with self._lock:
            self._require_link().send(cmd)


def simulator() -> Callable[[bytes], bytes | None]:
    """Firmware-shaped responder for ``simulated: true``."""

    def respond(data: bytes) -> bytes | None:
        line = data.decode("utf-8", "replace").strip()
        head = line.split("[", 1)[0]
        if head == "CN":
            return b"JP01-AVC01 Connected\n"
        if head == "DC":
            return b"JP01-AVC01 Disconnected\n"
        if head in ("GT", "ST"):
            return (
                b"--- STATUS UPDATE --- sim avc01 neopixel=0 "
                b"matrix=0 brightness=64\n"
            )
        if head in ("MN", "MM", "BM", "FN", "FM"):
            return f"ACK {head}\n".encode()
        return f"ERR unknown command: {line}\n".encode()

    return respond


__all__ = ["Avc01LightAdapter", "simulator"]
