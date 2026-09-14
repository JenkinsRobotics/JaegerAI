"""BusCatalog — what is running, and what does it talk to?

Every node announces itself on ``/sys/node/meta`` when it reaches
RUNNING. This collects those announcements into the answer ROS gives
with ``ros2 node list`` / ``ros2 topic info`` and JaegerOS previously
could not give at all: debugging a live graph meant reading source.

    catalog = BusCatalog(bus).attach()
    catalog.nodes()                  # {"animation": NodeMeta, ...}
    catalog.publishers_of("/act/display/frame")   # ["animation"]
    catalog.topics()                 # every topic anyone touches

Deliberately passive: it subscribes and listens. It never asks a node
for anything, so attaching a catalog cannot perturb the system it is
measuring — and a node that never announces simply is not in it, rather
than hanging the caller.

Late attach is handled by :meth:`request_announce`: nodes re-announce on
demand, so a surface opened an hour after boot still gets a full
picture.
"""

from __future__ import annotations

import threading
from typing import Any

from jaeger_os.transport import topics


class BusCatalog:
    """Collects ``NodeMeta`` announcements into a live graph view."""

    def __init__(self, bus: Any) -> None:
        self._bus = bus
        self._lock = threading.Lock()
        self._nodes: dict[str, topics.NodeMeta] = {}
        self._attached = False

    # ── lifecycle ────────────────────────────────────────────────

    def attach(self) -> "BusCatalog":
        if not self._attached:
            self._bus.subscribe(topics.SYS_NODE_META, self._on_meta)
            self._attached = True
        return self

    def detach(self) -> None:
        if not self._attached:
            return
        try:
            self._bus.unsubscribe(topics.SYS_NODE_META, self._on_meta)
        except Exception:  # noqa: BLE001
            pass
        self._attached = False

    def request_announce(self) -> None:
        """Ask every node to re-announce.

        A catalog attached after boot missed the announcements that
        already happened. Rather than persist them somewhere (which goes
        stale the moment a node restarts), ask again — the nodes are the
        source of truth about themselves."""
        try:
            self._bus.publish(topics.NodeMeta(node="", state="request"))
        except Exception:  # noqa: BLE001
            pass

    # ── queries ──────────────────────────────────────────────────

    def nodes(self) -> dict[str, topics.NodeMeta]:
        with self._lock:
            return dict(self._nodes)

    def topics(self) -> dict[str, dict[str, list[str]]]:
        """Every topic anyone touches -> who publishes and subscribes.

        A topic with publishers and no subscribers is output nobody
        reads; one with subscribers and no publishers is a consumer
        waiting for something that never comes. Both are bugs that are
        invisible without this view."""
        out: dict[str, dict[str, list[str]]] = {}
        with self._lock:
            metas = list(self._nodes.values())
        for meta in metas:
            for t in meta.publishes:
                out.setdefault(t, {"publishers": [], "subscribers": []})
                out[t]["publishers"].append(meta.node)
            for t in meta.subscribes:
                out.setdefault(t, {"publishers": [], "subscribers": []})
                out[t]["subscribers"].append(meta.node)
        for entry in out.values():
            entry["publishers"].sort()
            entry["subscribers"].sort()
        return out

    def publishers_of(self, topic: str) -> list[str]:
        return self.topics().get(topic, {}).get("publishers", [])

    def subscribers_of(self, topic: str) -> list[str]:
        return self.topics().get(topic, {}).get("subscribers", [])

    def orphan_topics(self) -> dict[str, list[str]]:
        """Topics with a producer but no consumer, or the reverse.

        The cheapest real bug-finder this view enables."""
        unread, unfed = [], []
        for name, entry in self.topics().items():
            if entry["publishers"] and not entry["subscribers"]:
                unread.append(name)
            elif entry["subscribers"] and not entry["publishers"]:
                unfed.append(name)
        return {"published_but_unread": sorted(unread),
                "subscribed_but_unfed": sorted(unfed)}

    def describe(self) -> str:
        """Human-readable dump — what a ``jaeger topics`` CLI prints."""
        lines: list[str] = []
        for name, meta in sorted(self.nodes().items()):
            lines.append(f"{name}  [{meta.node_class}]  {meta.state}  "
                         f"pid={meta.pid}")
            for t in meta.subscribes:
                lines.append(f"    <- {t}")
            for t in meta.publishes:
                lines.append(f"    -> {t}")
        return "\n".join(lines) if lines else "(no nodes announced)"

    # ── internals ────────────────────────────────────────────────

    def _on_meta(self, msg: Any) -> None:
        node = getattr(msg, "node", "")
        # The re-announce request rides the same topic with an empty
        # node name; it is a request, not an entry.
        if not node or getattr(msg, "state", "") == "request":
            return
        with self._lock:
            self._nodes[node] = msg


__all__ = ["BusCatalog"]
