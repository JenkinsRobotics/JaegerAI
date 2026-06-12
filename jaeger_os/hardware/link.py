"""Link — one controller connection: Transport × Protocol, with the
JP01 dual-path (primary + optional relay) and an RX reader thread.

The dual-path is a topology configuration, not code: on branch 2.0 of
JP01_Firmware the Jetson owns the serial ports and CC01-on-Mac relays
bracket commands over ZMQ (``main_controller.py:_has_live_zmq()``);
plugged in directly, the same commands ride serial. ``Link.open()``
tries the primary transport, then the relay; the active path is
visible in :meth:`descriptor` and health.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .protocol import Protocol, WireEvent
from .transport import Transport


class Link:
    def __init__(
        self,
        *,
        transport: Transport,
        protocol: Protocol,
        relay: Transport | None = None,
        on_event: Callable[[WireEvent], None] | None = None,
        rx_poll_s: float = 0.05,
        name: str = "link",
    ) -> None:
        self.name = name
        self.protocol = protocol
        self._primary = transport
        self._relay = relay
        self._active: Transport | None = None
        self._on_event = on_event
        self._rx_poll_s = rx_poll_s
        self._rx_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_rx_ts: float | None = None
        self.last_error: str = ""

    # ── lifecycle ───────────────────────────────────────────────────

    def open(self) -> None:
        """Open primary, falling back to the relay when configured.
        Raises only when EVERY path fails."""
        errors: list[str] = []
        for candidate in (self._primary, self._relay):
            if candidate is None:
                continue
            try:
                candidate.open()
                self._active = candidate
                break
            except Exception as exc:  # noqa: BLE001 — try the next path
                errors.append(f"{candidate.descriptor()}: {exc}")
        if self._active is None:
            self.last_error = "; ".join(errors) or "no transport configured"
            raise ConnectionError(f"{self.name}: {self.last_error}")
        self._stop.clear()
        if self._on_event is not None:
            self._rx_thread = threading.Thread(
                target=self._rx_loop, daemon=True,
                name=f"link-rx-{self.name}",
            )
            self._rx_thread.start()

    def close(self) -> None:
        self._stop.set()
        active, self._active = self._active, None
        if active is not None:
            active.close()

    @property
    def connected(self) -> bool:
        return self._active is not None and self._active.is_open()

    def descriptor(self) -> str:
        if self._active is None:
            return f"{self.name} (disconnected)"
        via = " via relay" if self._active is self._relay else ""
        return f"{self.name} → {self._active.descriptor()}{via}"

    # ── IO ──────────────────────────────────────────────────────────

    def send(self, command: Any) -> None:
        """Encode + write one command on the active path."""
        if self._active is None:
            raise ConnectionError(f"{self.name} not open")
        self._active.write_bytes(self.protocol.encode(command))

    def health(self) -> dict[str, Any]:
        age = (
            time.perf_counter() - self._last_rx_ts
            if self._last_rx_ts is not None else 0.0
        )
        return {
            "connected": self.connected,
            "path": self.descriptor(),
            "last_rx_age_s": round(age, 3),
            "last_error": self.last_error,
        }

    # ── RX ──────────────────────────────────────────────────────────

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            active = self._active
            if active is None:
                time.sleep(self._rx_poll_s)
                continue
            raw = active.read_bytes(timeout_s=self._rx_poll_s)
            if not raw:
                time.sleep(self._rx_poll_s)
                continue
            self._last_rx_ts = time.perf_counter()
            try:
                events = self.protocol.feed(raw)
            except Exception as exc:  # noqa: BLE001 — a bad frame never kills RX
                self.last_error = f"protocol: {exc}"
                continue
            for event in events:
                try:
                    self._on_event(event)  # type: ignore[misc]
                except Exception as exc:  # noqa: BLE001 — handler bugs never kill RX
                    self.last_error = f"handler: {exc}"


__all__ = ["Link"]
