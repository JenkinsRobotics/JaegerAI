"""Gateway Event Bus with durable replay and multi-client SSE.

Live subscribers receive in-process notifications. Replay uses the session
store when attached so reconnects and restarts share one event cursor.

Event schema — the ONE stream contract. The IDE, Mac app, CLI and WebUI all
render from these names; no client maintains a second schema. WebUI-specific
interactions (clarify cards, approval cards, dispatcher board updates) are
first-class event types here so nothing is lost when a client is only a
projection of this stream.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from jaeger_ai.contract.presence import ACTIVITY_STATES, DISPLAY

from .session_store import GatewaySessionStore


class ReplayGap(RuntimeError):
    """The client must reload its transcript because events were retired."""


#: First-class event names on the gateway stream. The bus itself accepts any
#: name (the store column is TEXT), but clients should render from this
#: registry: it is the union of what the IDE renders natively and what the
#: WebUI used to translate out of bridge frames. Adding a name here is the
#: contract for a new card/interaction; removing one is a breaking change.
EVENT_TYPES = frozenset({
    # Turn lifecycle (IDE + WebUI + CLI render these identically).
    "turn.start", "turn.delta", "turn.reasoning", "turn.reasoning.done", "turn.progress", "queue.updated",
    "turn.plan", "turn.steer", "turn.finish", "turn.failed", "turn.cancelled",
    "turn.unknown", "turn.cancel",
    # Tools and files.
    # The Gateway publishes tool.completed / tool.failed; tool.done / tool.error
    # are the older names some clients still accept.
    "tool.started", "tool.completed", "tool.failed", "tool.done", "tool.error", "files.changed",
    # Session lifecycle (the projection's list is built from these).
    "session.created", "session.updated", "session.deleted",
    # Owner/auto handoff of a session to an agent; ``agent.direct_chat`` is the
    # global twin of an owner handoff (Agents View sidebar).
    "session.handoff", "agent.direct_chat",
    # Approvals — the approval card. ``approval.request`` carries
    # {approval_id, kind, prompt, options, session_id}; resolve via
    # POST /v1/approvals/{id} which emits ``approval.resolved``.
    "approval.request", "approval.resolved",
    # Clarify cards — a mid-turn question the operator answers in place.
    # ``clarify.request`` carries {clarify_id, run_id, question, choices,
    # session_id}; the answer rides POST /v1/sessions/{id}/turns as a normal
    # turn or the dedicated respond endpoint, which emits ``clarify.resolved``.
    "clarify.request", "clarify.resolved",
    # Dispatcher board — kanban card moves surface here so a phone watching
    # the board sees the same updates the IDE does.
    "board.updated",
    # Tier 3 proactive delivery. Clients speak when ``speak`` is true;
    # DIGEST entries are visual/staged and never ring.
    "notification.proactive",
    # IDE bridge + attachments + agent lifecycle.
    "ide.request", "attachment.added",
    "agent.created", "agent.activated", "agent.handoff", "agent.handoff.finished",
    "agent.skills", "agent.knowledge", "project.created", "project.checked",
    # Sessions contract: every transcript row, and rolling summaries.
    "message.created", "session.summarized", "message.feedback", "message.reaction",
    "schedule.changed", "library.document.updated", "workflow.changed",
    # Durable task projection. The task owner is the authority; these are its
    # stream. ``jaeger.state`` is the presence projection (see contract/presence.py).
    "task.created", "task.updated", "jaeger.state",
    # Connect Apps panel: {id, state, audit?} on the global stream.
    "connect_app.updated",
    # Published by POST /v1/runtime/tier (was emitted but never registered).
    "runtime.tier.changed",
})

#: Names that carry a card the WebUI renders interactively. The adapter shim
#: forwards these verbatim; it never re-derives them from bridge frames.
CARD_EVENTS = frozenset({
    "approval.request", "approval.resolved",
    "clarify.request", "clarify.resolved",
    "board.updated",
})


@dataclass(frozen=True, slots=True)
class GatewayEvent:
    event_id: int
    session_id: str
    event: str
    data: dict[str, Any]
    timestamp: float


def _from_record(record: dict[str, Any]) -> GatewayEvent:
    return GatewayEvent(
        event_id=int(record["event_id"]),
        session_id=str(record["session_id"]),
        event=str(record["event"]),
        data=dict(record.get("data") or {}),
        timestamp=float(record["timestamp"]),
    )


class GatewayEventBus:
    def __init__(
        self,
        ring_buffer_size: int = 1000,
        store: GatewaySessionStore | None = None,
    ) -> None:
        self._seq = 0
        self._lock = threading.Lock()
        self._buffer: deque[GatewayEvent] = deque(maxlen=ring_buffer_size)
        self._subscribers: dict[asyncio.Event, tuple[str, asyncio.AbstractEventLoop]] = {}
        self.store = store
        if store is not None:
            store.event_listener = self.fanout

    def attach_store(self, store: GatewaySessionStore) -> None:
        self.store = store
        if store is not None:
            store.event_listener = self.fanout

    def publish(self, session_id: str, event: str, data: dict[str, Any]) -> GatewayEvent:
        if self.store is not None:
            evt = _from_record(self.store.append_event(session_id, event, data))
            with self._lock:
                self._seq = max(self._seq, evt.event_id)
                self._buffer.append(evt)
        else:
            with self._lock:
                self._seq += 1
                evt = GatewayEvent(
                    event_id=self._seq,
                    session_id=session_id,
                    event=event,
                    data=data,
                    timestamp=time.time(),
                )
                self._buffer.append(evt)

        self._fanout(evt)
        return evt

    def publish_state(
        self,
        session_id: str,
        state: str,
        *,
        task_id: str | None = None,
        status: str = "",
        intent: str = "",
        worker: str | None = None,
        approval_required: bool = False,
        **extra: Any,
    ) -> GatewayEvent:
        """Publish what Jaeger is doing as ``jaeger.state`` on the one stream."""
        if state not in ACTIVITY_STATES:
            raise ValueError(f"unknown activity state: {state!r}")
        return self.publish(session_id, "jaeger.state", {
            "state": state, "session_id": session_id, "task_id": task_id, "status": status,
            "intent": intent, "worker": worker, "approval_required": approval_required,
            "display": DISPLAY[state], **extra,
        })

    def fanout(self, record: dict[str, Any] | GatewayEvent) -> GatewayEvent:
        """Notify live subscribers of an event already persisted by the store."""
        evt = record if isinstance(record, GatewayEvent) else _from_record(record)
        with self._lock:
            self._seq = max(self._seq, evt.event_id)
            self._buffer.append(evt)
        self._fanout(evt)
        return evt

    def _fanout(self, evt: GatewayEvent) -> None:
        # Notifications are coalesced; the durable log remains the source of
        # events. Slow clients never silently lose a queue entry or hang.
        with self._lock:
            subscribers = list(self._subscribers.items())
        for wake, (session, loop) in subscribers:
            if evt.session_id not in {session, "*"}:
                continue
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                with self._lock:
                    self._subscribers.pop(wake, None)

    def get_replay_events(self, session_id: str, since_event_id: int = 0) -> list[GatewayEvent]:
        if self.store is not None:
            replay = self.store.replay_events(session_id, since_event_id, limit=5000)
            return [_from_record(item) for item in replay["events"]]
        with self._lock:
            return [
                e for e in self._buffer
                if e.session_id in {session_id, "*"} and e.event_id > since_event_id
            ]

    def replay_window(self, session_id: str, since_event_id: int = 0) -> dict[str, Any]:
        if self.store is not None:
            return self.store.replay_events(session_id, since_event_id)
        events = self.get_replay_events(session_id, since_event_id)
        return {
            "events": [
                {
                    "event_id": e.event_id,
                    "session_id": e.session_id,
                    "event": e.event,
                    "data": e.data,
                    "timestamp": e.timestamp,
                }
                for e in events
            ],
            "cursor_expired": False,
            "oldest_event_id": events[0].event_id if events else None,
            "latest_event_id": events[-1].event_id if events else None,
            "valid_cursor": True,
        }

    async def subscribe(
        self,
        session_id: str,
        since_event_id: int = 0,
    ) -> AsyncGenerator[GatewayEvent, None]:
        wake = asyncio.Event()
        with self._lock:
            self._subscribers[wake] = (session_id, asyncio.get_running_loop())

        try:
            last_id = since_event_id
            while True:
                wake.clear()
                window = self.replay_window(session_id, last_id)
                if window["cursor_expired"]:
                    raise ReplayGap("Event cursor expired; reload session transcript")
                records = window["events"]
                if records:
                    for record in records:
                        evt = _from_record(record)
                        last_id = evt.event_id
                        yield evt
                    # Drain every page before waiting for another publish.
                    continue
                try:
                    # Also notice events committed by a different process.
                    await asyncio.wait_for(wake.wait(), timeout=1.0)
                except TimeoutError:
                    pass
        finally:
            with self._lock:
                self._subscribers.pop(wake, None)


def latest_presence(store: Any) -> dict[str, Any] | None:
    """The newest durable ``jaeger.state`` across sessions (a read; for avatars)."""
    return store.latest_event("jaeger.state") if store is not None else None


def project_presence(events: Any, *, session_id: str) -> dict[str, Any]:
    """The latest ``jaeger.state`` for a session, for avatars and phones to read.

    A pure read of the stream. Nothing here writes state back.
    """
    latest: dict[str, Any] | None = None
    for evt in events:
        name = getattr(evt, "event", None) if not isinstance(evt, dict) else evt.get("event")
        if name != "jaeger.state":
            continue
        data = getattr(evt, "data", None) if not isinstance(evt, dict) else evt.get("data")
        if isinstance(data, dict) and data.get("session_id") in (None, "", session_id):
            latest = data
    if not latest or latest.get("state") not in ACTIVITY_STATES:
        return {"state": "idle", "display": DISPLAY["idle"], "owner_needed": False,
                "task_id": None, "session_id": session_id}
    state = latest["state"]
    return {"state": state, "display": DISPLAY[state], "task_id": latest.get("task_id"),
            "owner_needed": state == "needs_owner" or bool(latest.get("approval_required")),
            "session_id": session_id}
