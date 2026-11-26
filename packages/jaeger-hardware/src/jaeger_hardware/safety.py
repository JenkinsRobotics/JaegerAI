"""L2 system e-stop latch promoted & decoupled from JROS (`jaeger_os/hardware/safety.py`).

Engaging latches immediately and fires all registered L1 node stops; motion
capabilities refuse fail-closed while latched; release requires explicit
``source="operator"`` so no autonomous agent can un-stop physical actuators.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable


class EStopLatch:
    """Process-local L2 e-stop latch with L1 node stop callbacks and operator-only release."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engaged = False
        self._reason = ""
        self._source = ""
        self._since: float | None = None
        self._stops: list[tuple[str, Callable[[], None]]] = []

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._engaged

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "engaged": self._engaged,
                "reason": self._reason,
                "source": self._source,
                "since_s": (
                    round(time.monotonic() - self._since, 1)
                    if self._engaged and self._since is not None
                    else 0.0
                ),
            }

    def refusal(self) -> str:
        s = self.status()
        return (
            f"e-stop latched ({s['reason'] or 'no reason recorded'}, "
            f"source={s['source'] or 'unknown'}) — motion refused; "
            "release requires an explicit operator action"
        )

    def register_stop(self, name: str, stop_fn: Callable[[], None]) -> None:
        with self._lock:
            self._stops.append((name, stop_fn))

    def engage(self, reason: str, *, source: str = "operator") -> None:
        with self._lock:
            already = self._engaged
            self._engaged = True
            if not already:
                self._reason = reason
                self._source = source
                self._since = time.monotonic()
            stops = list(self._stops)
        if already:
            return
        for name, stop_fn in stops:
            try:
                stop_fn()
            except Exception as exc:  # noqa: BLE001
                print(f"[estop] L1 stop for {name} raised: {exc}", file=sys.stderr, flush=True)

    def release(self, *, source: str = "operator") -> None:
        if source != "operator":
            raise PermissionError(
                f"e-stop release denied for source={source!r} — only the operator releases the latch"
            )
        with self._lock:
            self._engaged = False
            self._reason = ""
            self._source = ""
            self._since = None


__all__ = ["EStopLatch"]
