"""NodeHealth heartbeats + the liveness cache.

Vocabulary is the Kubernetes split: *liveness* = heartbeats arriving
on ``/sense/node_health`` (and, for subprocess nodes, the process being
alive); *readiness* = whatever the app's capability layer derives
from the cached details. The cache is the HostMonitor idea — one
subscriber holds the latest health per node so surfaces and the
supervisor ask a dict instead of each holding subscriptions.

Canon type (0.8 U3): ``jaeger_os.transport.topics.NodeHealth`` — a
msgspec ``Struct`` — on ``topics.SENSE_NODE_HEALTH`` (``/sense/node_health``).
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
        bus.subscribe(topics.SENSE_NODE_HEALTH, self._on_health)

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


__all__ = ["HealthCache"]
