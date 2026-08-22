"""L2 system e-stop — the latched ``/act/estop`` topic.

Three-layer contract (plan §2.8): L0 is a firmware watchdog (the only
layer with a hard latency bound — absent from MC01 today, REQUIRED
before live motors leave beta); L1 is each node's queue-bypassing
``estop()``; L2 — this module — is the bus-wide latch. Publishing
``EStop(engaged=True)`` latches; every registered node stop runs on
receipt; motion capabilities refuse while latched; release is an
explicit operator action, never automatic.

Honest budget statement (also in the plan): L2 → L1 through Python is
best-effort — tens of ms in-process, unbounded under GC/load. This
latch is a coordination layer, not a hard real-time guarantee.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from jaeger_os.transport import topics
from jaeger_os.transport import Bus


class EStopLatch:
    """Process-local view of the system e-stop state.

    Wire one per process that hosts hardware nodes or capability
    tools. It subscribes to ``/act/estop``; any publisher anywhere on
    the bus latches it. Node-local stop callbacks registered via
    :meth:`register_stop` run on engage — each callback must be the
    node's L1 path (queue-bypassing immediate write), and a callback
    that raises never blocks the others.

    Release policy: an ``engaged=False`` message releases the latch
    ONLY when its ``source`` is ``"operator"`` — the agent or a
    confused node cannot un-stop the robot by publishing.
    """

    def __init__(self, bus: Bus | None = None) -> None:
        self._bus = bus
        self._lock = threading.Lock()
        self._engaged = False
        self._reason = ""
        self._source = ""
        self._since: float | None = None
        self._stops: list[tuple[str, Callable[[], None]]] = []
        if bus is not None:
            bus.subscribe(topics.ACT_ESTOP, self._on_estop)

    # ── state ───────────────────────────────────────────────────────

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
                    if self._engaged and self._since is not None else 0.0
                ),
            }

    def refusal(self) -> str:
        """The fail-closed message a motion capability returns while
        latched."""
        s = self.status()
        return (
            f"e-stop latched ({s['reason'] or 'no reason recorded'}, "
            f"source={s['source'] or 'unknown'}) — motion refused; "
            "release requires an explicit operator action"
        )

    # ── node registration ───────────────────────────────────────────

    def register_stop(self, name: str, stop_fn: Callable[[], None]) -> None:
        """Register a node's L1 stop to run on engage. ``name`` is the
        controller key (for error attribution)."""
        with self._lock:
            self._stops.append((name, stop_fn))

    # ── engage / release ────────────────────────────────────────────

    def engage(self, reason: str, *, source: str = "operator") -> None:
        """Latch locally, run L1 stops, and broadcast on the bus so
        every other process latches too."""
        self._apply_engage(reason, source)
        if self._bus is not None:
            self._bus.publish(topics.EStop(
                engaged=True, reason=reason, source=source,
            ))

    def release(self, *, source: str = "operator") -> None:
        """Explicit operator release. Refuses for any other source."""
        if source != "operator":
            raise PermissionError(
                f"e-stop release denied for source={source!r} — "
                "only the operator releases the latch"
            )
        with self._lock:
            self._engaged = False
            self._reason = ""
            self._source = ""
            self._since = None
        if self._bus is not None:
            self._bus.publish(topics.EStop(
                engaged=False, reason="released", source=source,
            ))

    # ── bus side ────────────────────────────────────────────────────

    def _on_estop(self, msg: Any) -> None:
        engaged = bool(getattr(msg, "engaged", True))
        source = str(getattr(msg, "source", ""))
        if engaged:
            self._apply_engage(
                str(getattr(msg, "reason", "")), source,
            )
        elif source == "operator":
            with self._lock:
                self._engaged = False
                self._reason = ""
                self._source = ""
                self._since = None

    def _apply_engage(self, reason: str, source: str) -> None:
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
            except Exception as exc:  # noqa: BLE001 — one bad stop never blocks the rest
                import sys
                print(
                    f"[estop] L1 stop for {name} raised: {exc}",
                    file=sys.stderr, flush=True,
                )


__all__ = ["EStopLatch"]
