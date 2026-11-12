"""Feed the observing lifecycle hooks from the Gateway's one event stream.

``on_approval``, ``on_error`` and ``on_turn_end`` (jaeger_agent.hooks) see the
exact events the interface sees, in commit order, once per event_id.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from jaeger_agent.hooks import HookRegistry, registry as default_registry

APPROVAL = frozenset({"approval.request", "approval.resolved"})
ERROR = frozenset({"tool.failed", "turn.failed", "turn.unknown"})
TURN_END = frozenset({"turn.finish", "turn.failed", "turn.cancelled", "turn.unknown"})


def install(bus: Any, registry: HookRegistry | None = None) -> None:
    reg = registry or default_registry
    seen: deque[int] = deque(maxlen=512)

    def observe(evt: Any) -> None:
        if evt.event_id in seen:
            return
        name = evt.event
        model_failed = name == "model.finished" and (evt.data or {}).get("ok") is False
        if name not in APPROVAL and name not in ERROR and name not in TURN_END and not model_failed:
            return
        seen.append(evt.event_id)
        payload = {"event": name, "event_id": evt.event_id, "session_id": evt.session_id,
                   "timestamp": evt.timestamp, "data": dict(evt.data or {})}
        if name in APPROVAL:
            reg.fire("on_approval", payload)
        if name in ERROR or model_failed:
            reg.fire("on_error", payload)
        if name in TURN_END:
            reg.fire("on_turn_end", payload)

    bus.add_observer(observe)
