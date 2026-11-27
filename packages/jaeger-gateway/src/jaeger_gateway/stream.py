"""Zombie-fenced SSE event streaming with monotonic Last-Event-ID cursor replay (Agno pattern)."""

from __future__ import annotations

import json
import threading
from typing import Any, Mapping

from jaeger_events import FencedEventStream, StaleWriterError


def format_sse(
    *,
    event: str,
    data: Mapping[str, Any] | str,
    seq: int | None = None,
) -> str:
    """Render one standards-compliant Server-Sent Event frame."""
    lines: list[str] = []
    if seq is not None:
        lines.append(f"id: {int(seq)}")
    if event:
        lines.append(f"event: {event}")
    payload = data if isinstance(data, str) else json.dumps(dict(data), ensure_ascii=False, default=str)
    for chunk in payload.splitlines() or [""]:
        lines.append(f"data: {chunk}")
    return "\n".join(lines) + "\n\n"


class SessionEventHub:
    """Manages per-session zombie-fenced event streams with cursor-based replay."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stream = FencedEventStream()
        self._doorbells: dict[str, threading.Condition] = {}
        self._requests: dict[str, str] = {}

    def _cond(self, session_id: str) -> threading.Condition:
        with self._lock:
            cond = self._doorbells.get(session_id)
            if cond is None:
                cond = threading.Condition(self._lock)
                self._doorbells[session_id] = cond
            return cond

    def open_generation(self, session_id: str, *, floor_seq: int = 0, request_id: str = "") -> int:
        """Mint a new monotonic writer generation, fencing out any prior zombie worker."""
        cond = self._cond(session_id)
        with cond:
            gen = self._stream.open_attempt(session_id, floor_seq=floor_seq)
            if request_id:
                self._requests[session_id] = request_id
            else:
                self._requests.pop(session_id, None)
            cond.notify_all()
            return gen

    def publish(
        self,
        session_id: str,
        event: str,
        payload: Mapping[str, Any],
        *,
        generation: int,
    ) -> dict[str, Any]:
        """Append a fenced event and ring the session doorbell. Raises StaleWriterError on zombie writes."""
        cond = self._cond(session_id)
        with cond:
            request_id = self._requests.get(session_id)
            if request_id and "request_id" not in payload:
                payload = {**payload, "request_id": request_id}
            env = self._stream.append(
                session_id,
                generation,
                event,
                payload,
                session_id=session_id,
            )
            rec = {
                "seq": env.seq,
                "event": env.event_type,
                "payload": dict(env.payload),
                "session_id": env.session_id,
            }
            cond.notify_all()
            return rec

    def replay_after(self, session_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        envs = self._stream.read_since(session_id, after_seq=after_seq)
        return [
            {
                "seq": env.seq,
                "event": env.event_type,
                "payload": dict(env.payload),
                "session_id": env.session_id,
            }
            for env in envs
        ]

    def wait_for_events(
        self,
        session_id: str,
        after_seq: int,
        *,
        timeout: float = 15.0,
    ) -> list[dict[str, Any]]:
        """Block on the session doorbell until events > ``after_seq`` arrive or timeout expires."""
        cond = self._cond(session_id)
        with cond:
            items = self.replay_after(session_id, after_seq=after_seq)
            if items:
                return items
            cond.wait(timeout=max(0.01, float(timeout)))
            return self.replay_after(session_id, after_seq=after_seq)


__all__ = ["SessionEventHub", "StaleWriterError", "format_sse"]
