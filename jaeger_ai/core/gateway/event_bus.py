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
    "turn.start", "turn.delta", "turn.reasoning", "turn.progress",
    "turn.plan", "turn.finish", "turn.failed", "turn.cancelled",
    "turn.unknown", "turn.cancel",
    # Tools and files.
    "tool.started", "tool.done", "tool.error", "files.changed",
    # Session lifecycle (the projection's list is built from these).
    "session.created", "session.updated", "session.deleted",
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
    # IDE bridge + attachments + agent lifecycle.
    "ide.request", "attachment.added",
    "agent.created", "agent.activated", "agent.handoff", "agent.handoff.finished",
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

    def attach_store(self, store: GatewaySessionStore) -> None:
        self.store = store

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
