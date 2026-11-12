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
TURN_START = frozenset({"turn.start"})
SESSION_START = frozenset({"session.created"})
WATCHED = APPROVAL | ERROR | TURN_END | TURN_START | SESSION_START


def install(bus: Any, registry: HookRegistry | None = None) -> None:
    reg = registry or default_registry
    if registry is None:
        try:  # old plugin hooks ride the same registry (one dispatch path)
            from jaeger_ai.plugins.registry import install_agent_hook_bridge
            install_agent_hook_bridge()
        except Exception:  # noqa: BLE001
            pass
    seen: deque[int] = deque(maxlen=512)

    def observe(evt: Any) -> None:
        if evt.event_id in seen:
            return
        name = evt.event
        model_failed = name == "model.finished" and (evt.data or {}).get("ok") is False
        if name not in WATCHED and not model_failed:
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
        if name in TURN_START:
            reg.fire("on_turn_start", payload)
        if name in SESSION_START:
            reg.fire("on_session_start", payload)

    bus.add_observer(observe)
