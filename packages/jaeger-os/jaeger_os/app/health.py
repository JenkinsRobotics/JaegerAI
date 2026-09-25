"""NodeHealth heartbeats + the liveness cache.

Vocabulary is the Kubernetes split: *liveness* = heartbeats arriving
on ``/sys/node/health`` (and, for subprocess nodes, the process being
alive); *readiness* = whatever the app's capability layer derives
from the cached details. The cache is the HostMonitor idea — one
subscriber holds the latest health per node so surfaces and the
supervisor ask a dict instead of each holding subscriptions.

Canon type (0.8 U3): ``jaeger_os.transport.topics.NodeHealth`` — a
msgspec ``Struct`` — on ``topics.SYS_NODE_HEALTH`` (``/sys/node/health``).
Before U3 this module carried its OWN plain-dataclass ``NodeHealth`` on a
DIFFERENT topic (``/sys/node_health``) that nothing published — every
``nodes.base.Node`` now heartbeats on the real topic (see
``nodes/base.py`` ``Node.run()``), so this cache listens there instead
of a topic nobody wrote to.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from jaeger_os.transport import topics


#: A node heartbeats about once a second, so three missed beats is a
#: node that has stopped, not one that is briefly busy.
STALE_AFTER_S = 3.0

#: Ascending severity — ``max()`` over this ordering is the rollup rule.
_SEVERITY_ORDER = (
    topics.HEALTH_OK,
    topics.HEALTH_WARN,
    topics.HEALTH_STALE,   # gone quiet: worse than degraded...
    topics.HEALTH_ERROR,   # ...but a reported error is worse still
)


class HealthCache:
    """Latest ``topics.NodeHealth`` per node + age accounting.

    Stores the raw msgspec message as-is (not a dict) — callers read
    whatever fields the canon type carries (``state``, ``detail``,
    ``link_connected``, ``last_controller_rx_age_s``).
    """

    def __init__(self, bus: Any) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, Any] = {}
        self._ts: dict[str, float] = {}
        bus.subscribe(topics.SYS_NODE_HEALTH, self._on_health)

    def _on_health(self, msg: Any) -> None:
        node = getattr(msg, "node", "")
        if not node:
            return
        with self._lock:
            self._latest[node] = msg
            self._ts[node] = time.time()

    def latest(self, node: str) -> Any | None:
        with self._lock:
            return self._latest.get(node)

    def age_s(self, node: str) -> float | None:
        """Seconds since the last heartbeat, or None if never seen."""
        with self._lock:
            ts = self._ts.get(node)
        if ts is None:
            return None
        return max(0.0, time.time() - ts)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest)

    # ── severity ─────────────────────────────────────────────────

    def level_for(self, node: str, *, stale_after_s: float = STALE_AFTER_S,
                  ) -> str:
        """Severity for ``node``, including the one a node cannot report.

        A node that has stopped heartbeating cannot tell you it stopped —
        that judgement needs a consumer watching the clock, which is
        this. Everything else is the node's own reported level.
        """
        with self._lock:
            msg = self._latest.get(node)
            ts = self._ts.get(node)
        if msg is None or ts is None:
            return topics.HEALTH_STALE
        if time.time() - ts > stale_after_s:
            return topics.HEALTH_STALE
        return getattr(msg, "level", topics.HEALTH_OK) or topics.HEALTH_OK

    def system_level(self, *, stale_after_s: float = STALE_AFTER_S) -> str:
        """The single answer to "is the robot healthy?".

        Worst level wins. Without this, that question has no answer at
        all: a caller has to fetch every node and decide for itself what
        an aggregate means, and each caller decides differently.
        """
        levels = [self.level_for(n, stale_after_s=stale_after_s)
                  for n in self.snapshot()]
        if not levels:
            return topics.HEALTH_STALE
        return max(levels, key=_SEVERITY_ORDER.index)

    def unhealthy(self, *, stale_after_s: float = STALE_AFTER_S,
                  ) -> dict[str, str]:
        """Just the nodes that are not OK, and why — what an operator
        surface shows instead of a wall of green."""
        out = {}
        for node in self.snapshot():
            level = self.level_for(node, stale_after_s=stale_after_s)
            if level != topics.HEALTH_OK:
                out[node] = level
        return out


__all__ = ["HealthCache", "STALE_AFTER_S"]
