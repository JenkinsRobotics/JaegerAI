"""adapters.py — LED / light adapters.

Generic Protocol + a reference ASCII-line implementation.  Real
boards (Teensy NeoPixel, WLED, etc.) subclass the serial adapter
or implement the Protocol directly with HTTP / MQTT / vendor SDK
calls.
"""

from __future__ import annotations

import threading
from typing import Protocol


class LightAdapter(Protocol):
    """The interface the light node depends on."""

    def start(self) -> None:
        """Open the link to the LED controller."""
        ...

    def stop(self) -> None:
        """Close the link; should blank the strip on shutdown to
        avoid the post-crash 'still glowing' UX."""
        ...

    def send_pattern(
        self,
        *,
        strip_id: str,
        rgb: list[int],
        pattern: str,
        duration_ms: int,
    ) -> None:
        """Apply a colour + pattern to a named strip.

        ``rgb`` is 3 ints in [0, 255].
        ``pattern`` is one of ``"solid" | "pulse" | "rainbow" | "off"``.
        ``duration_ms == 0`` means hold until the next command.
        """
        ...


class SerialLightAdapter:
    """Reference adapter for an LED controller that speaks ASCII over
    USB-CDC or TCP.

    Default protocol (universal, no JP01 specifics):
        LED <strip_id> <r> <g> <b> <pattern> <duration_ms>\\n
        OFF <strip_id>\\n

    Subclass and override ``_format_*`` to match your firmware.
    """

    def __init__(self, *, write_line=None) -> None:
        self._write_line = write_line or (lambda b: None)
        self._lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        # Blank all known strips on shutdown by emitting an OFF
        # broadcast (strip_id "*").  Adapter subclasses can
        # override if their firmware doesn't accept wildcards.
        try:
            self._write(self._format_off(strip_id="*"))
        except Exception:  # noqa: BLE001
            pass
        self._started = False

    def send_pattern(
        self,
        *,
        strip_id: str,
        rgb: list[int],
        pattern: str,
        duration_ms: int,
    ) -> None:
        if len(rgb) != 3:
            raise ValueError(
                f"send_pattern: rgb must be [r, g, b]; got {rgb!r}"
            )
        if pattern == "off":
            self._write(self._format_off(strip_id=strip_id))
            return
        self._write(self._format_pattern(
            strip_id=strip_id,
            r=int(rgb[0]), g=int(rgb[1]), b=int(rgb[2]),
            pattern=pattern,
            duration_ms=int(duration_ms),
        ))

    def _format_pattern(
        self, *, strip_id, r, g, b, pattern, duration_ms,
    ) -> bytes:
        return (
            f"LED {strip_id} {r} {g} {b} {pattern} {duration_ms}\n"
        ).encode("ascii")

    def _format_off(self, *, strip_id) -> bytes:
        return f"OFF {strip_id}\n".encode("ascii")

    def _write(self, line: bytes) -> None:
        with self._lock:
            self._write_line(line)
