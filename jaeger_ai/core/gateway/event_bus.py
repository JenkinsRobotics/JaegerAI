"""Gateway Event Bus with Ring Buffer & Multi-Client Replay.

Allows multiple clients (Mac app, Web UI, terminal) to subscribe to the same
session event stream simultaneously. Modeled after OpenClaw's event bus.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, AsyncGenerator


@dataclass(frozen=True, slots=True)
class GatewayEvent:
    event_id: int
    session_id: str
    event: str
    data: dict[str, Any]
    timestamp: float


class GatewayEventBus:
    def __init__(self, ring_buffer_size: int = 1000) -> None:
        self._seq = 0
        self._lock = threading.Lock()
        self._buffer: deque[GatewayEvent] = deque(maxlen=ring_buffer_size)
        self._subscribers: set[asyncio.Queue[GatewayEvent]] = set()

    def publish(self, session_id: str, event: str, data: dict[str, Any]) -> GatewayEvent:
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

        # Notify active async queues
        dead: list[asyncio.Queue[GatewayEvent]] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(evt)
            except (asyncio.QueueFull, RuntimeError):
                dead.append(q)

        for d in dead:
            self._subscribers.discard(d)

        return evt

    def get_replay_events(self, session_id: str, since_event_id: int = 0) -> list[GatewayEvent]:
        with self._lock:
            return [
                e for e in self._buffer
                if e.session_id == session_id and e.event_id > since_event_id
            ]

    async def subscribe(
        self,
        session_id: str,
        since_event_id: int = 0,
    ) -> AsyncGenerator[GatewayEvent, None]:
        queue: asyncio.Queue[GatewayEvent] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)

        try:
            # First yield replay events
            for old_evt in self.get_replay_events(session_id, since_event_id):
                yield old_evt

            # Then stream new events
            while True:
                evt = await queue.get()
                if evt.session_id == session_id or evt.session_id == "*":
                    yield evt
        finally:
            self._subscribers.discard(queue)
