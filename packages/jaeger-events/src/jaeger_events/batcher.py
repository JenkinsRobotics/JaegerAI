"""Frame-aligned StreamingDeltaBatcher (OpenHands pattern).

Coalesces high-frequency token deltas (text, thinking, tool-arg chunks) to avoid
UI/SSE re-render storms while guaranteeing that buffered deltas ALWAYS flush
strictly before any durable frame (tool call, observation, turn completion).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from jaeger_contracts import EventEnvelope


@dataclass
class _PendingDelta:
    session_id: str
    stream_key: str
    chunks: list[str]


class StreamingDeltaBatcher:
    """Coalesces consecutive string deltas per (session_id, stream_key)."""

    def __init__(
        self,
        emit_fn: Callable[[str, Mapping[str, Any]], None],
        *,
        max_buffer_chars: int = 512,
    ) -> None:
        self._emit = emit_fn
        self._max_chars = max(1, int(max_buffer_chars))
        self._pending: _PendingDelta | None = None
        self._pending_chars: int = 0

    def push_delta(self, session_id: str, stream_key: str, text: str) -> None:
        if not text:
            return
        if (
            self._pending is not None
            and (self._pending.session_id != session_id or self._pending.stream_key != stream_key)
        ):
            self.flush()

        if self._pending is None:
            self._pending = _PendingDelta(session_id=session_id, stream_key=stream_key, chunks=[text])
            self._pending_chars = len(text)
        else:
            self._pending.chunks.append(text)
            self._pending_chars += len(text)

        if self._pending_chars >= self._max_chars:
            self.flush()

    def push_durable(self, envelope: EventEnvelope) -> None:
        """Flush any buffered deltas BEFORE forwarding a durable event."""
        self.flush()
        self._emit(envelope.event_type, {
            "seq": envelope.seq,
            "session_id": envelope.session_id,
            "payload": dict(envelope.payload),
            "durable": envelope.durable,
        })

    def flush(self) -> None:
        if self._pending is None:
            return
        merged = "".join(self._pending.chunks)
        session_id = self._pending.session_id
        stream_key = self._pending.stream_key
        self._pending = None
        self._pending_chars = 0
        self._emit("delta.batch", {
            "session_id": session_id,
            "stream_key": stream_key,
            "text": merged,
            "durable": False,
        })
