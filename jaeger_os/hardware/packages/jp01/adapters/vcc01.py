"""VCC01 — Jetson vision computer adapter (REP command side).

The Jetson's high-rate surfaces (PUB telemetry :5555/:5558, UDP video
:5001/:5003) deliberately do NOT ride a Link (plan §2.3) — they go
straight onto the bus via a subscriber-thread node when the live
vision path lands. What this adapter owns today is the REQ/REP
command channel (JSON lines) and the stream *directory* the
``robot_vision(action='stream_info')`` capability reports.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from jaeger_os.hardware.link import Link
from jaeger_os.hardware.protocol import WireEvent


class Vcc01VisionAdapter:
    def __init__(self, *, streams: dict[str, Any] | None = None) -> None:
        self.streams = dict(streams or {})
        self._link: Link | None = None
        self._last_reply: dict[str, Any] = {}
        self._last_reply_ts: float | None = None

    def attach_link(self, link: Link) -> None:
        self._link = link

    def on_wire_event(self, event: WireEvent) -> None:
        if event.kind == "json":
            self._last_reply = event.data
            self._last_reply_ts = time.monotonic()

    def start(self) -> None:
        link = self._require_link()
        if not link.connected:
            link.open()

    def stop(self) -> None:
        link = self._link
        if link is None:
            return
        link.close()

    def stream_info(self) -> dict[str, Any]:
        return {
            "controller": "vcc01",
            "streams": self.streams,
            "link": (self._link.health() if self._link else {}),
        }

    def telemetry(self) -> dict[str, Any]:
        age = (
            round(time.monotonic() - self._last_reply_ts, 1)
            if self._last_reply_ts is not None else None
        )
        return {
            "controller": "vcc01",
            "last_reply": self._last_reply,
            "reply_age_s": age,
            "streams": self.streams,
            "link": (self._link.health() if self._link else {}),
        }

    def _require_link(self) -> Link:
        if self._link is None:
            raise ConnectionError("vcc01 adapter has no link attached")
        return self._link


def simulator() -> Callable[[bytes], bytes | None]:
    """JSON-line responder for ``simulated: true``."""

    def respond(data: bytes) -> bytes | None:
        text = data.decode("utf-8", "replace").strip()
        return (
            b'{"ok": true, "sim": true, "echo": '
            + repr(text).replace("'", '"').encode()
            + b"}\n"
        )

    return respond


__all__ = ["Vcc01VisionAdapter", "simulator"]
