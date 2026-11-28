"""In-process Global Real-Time Event Spine for instant multi-device & Office/Droid/MC sync.

Zero external message brokers (no Redis/RabbitMQ): uses a bounded ring buffer and
thread-safe asyncio queue fan-out so every connected Mac/iPad tab, Virtual Office,
Mind Panel, and Droid view updates the millisecond state changes anywhere in Jaeger.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any, Mapping


class GlobalEventBus:
    """Thread-safe monotonic pub/sub event bus bridging sync workers and async SSE streams."""

    def __init__(self, *, max_history: int = 120) -> None:
        self._lock = threading.RLock()
        self._seq = 0
        self._history: deque[dict[str, Any]] = deque(maxlen=max(20, int(max_history)))
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = []

    def publish(self, event: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Publish an event from any thread and wake all connected SSE clients immediately."""
        with self._lock:
            self._seq += 1
            rec = {
                "seq": self._seq,
                "event": str(event or "system.update"),
                "payload": dict(payload or {}),
                "timestamp": time.time(),
            }
            self._history.append(rec)
            subs = list(self._subscribers)

        for loop, queue in subs:
            try:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(self._safe_put, queue, rec)
            except RuntimeError:
                pass
        return rec

    @staticmethod
    def _safe_put(queue: asyncio.Queue[dict[str, Any]], rec: dict[str, Any]) -> None:
        try:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(rec)
        except Exception:  # noqa: BLE001
            pass

    def recent(self, *, after_seq: int = 0, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            items = [e for e in self._history if int(e["seq"]) > int(after_seq)]
            return items[-max(1, int(limit)):]

    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def subscribe(self) -> tuple[asyncio.Queue[dict[str, Any]], int]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=128)
        with self._lock:
            self._subscribers.append((loop, q))
            return q, self._seq

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers = [(lp, q) for (lp, q) in self._subscribers if q is not queue]


__all__ = ["GlobalEventBus"]
