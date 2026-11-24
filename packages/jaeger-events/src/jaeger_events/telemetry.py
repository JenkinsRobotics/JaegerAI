"""Non-blocking background telemetry queue + W3C traceparent helpers.

Harvested from:
- hermes-agent (`monitoring/emitter.py`): bounded non-blocking queue that drops
  telemetry rather than ever stalling the agent turn loop.
- goose (`otel/trace_context.rs`): W3C `traceparent` header generation and
  parsing for propagating trace context across MCP/A2A tool boundaries.
"""

from __future__ import annotations

import queue
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class TraceContext:
    """W3C Trace Context (`00-<32hex trace_id>-<16hex span_id>-01`)."""

    trace_id: str
    span_id: str
    sampled: bool = True

    @classmethod
    def new_root(cls, *, sampled: bool = True) -> "TraceContext":
        return cls(
            trace_id=secrets.token_hex(16),
            span_id=secrets.token_hex(8),
            sampled=sampled,
        )

    def child_span(self) -> "TraceContext":
        return TraceContext(
            trace_id=self.trace_id,
            span_id=secrets.token_hex(8),
            sampled=self.sampled,
        )

    def to_traceparent(self) -> str:
        flags = "01" if self.sampled else "00"
        return f"00-{self.trace_id}-{self.span_id}-{flags}"

    def to_headers(self) -> dict[str, str]:
        return {"traceparent": self.to_traceparent()}

    @classmethod
    def from_traceparent(cls, header: str) -> "TraceContext | None":
        parts = (header or "").strip().split("-")
        if len(parts) != 4 or parts[0] != "00":
            return None
        trace_id, span_id, flags = parts[1], parts[2], parts[3]
        if len(trace_id) != 32 or len(span_id) != 16 or len(flags) != 2:
            return None
        try:
            int(trace_id, 16)
            int(span_id, 16)
            flag_int = int(flags, 16)
        except ValueError:
            return None
        return cls(trace_id=trace_id.lower(), span_id=span_id.lower(), sampled=bool(flag_int & 1))


@dataclass(frozen=True)
class SpanRecord:
    """Lightweight OTel-compatible span record for local or OTLP/HTTP export."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str = ""
    start_time_ns: int = field(default_factory=time.time_ns)
    end_time_ns: int = 0
    attributes: Mapping[str, Any] = field(default_factory=dict)
    status: str = "OK"


class TelemetryEmitter:
    """Bounded non-blocking background telemetry queue (never stalls turn loop)."""

    def __init__(
        self,
        sink: Callable[[SpanRecord], None],
        *,
        max_queue: int = 1024,
    ) -> None:
        self._sink = sink
        self._q: queue.Queue[SpanRecord | None] = queue.Queue(maxsize=max(8, max_queue))
        self._dropped: int = 0
        self._delivered: int = 0
        self._closed = False
        self._worker = threading.Thread(target=self._run, name="jaeger-telemetry", daemon=True)
        self._worker.start()

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def delivered(self) -> int:
        return self._delivered

    def emit(self, record: SpanRecord) -> bool:
        if self._closed:
            return False
        try:
            self._q.put_nowait(record)
            return True
        except queue.Full:
            self._dropped += 1
            return False

    def flush(self, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while not self._q.empty() and time.monotonic() < deadline:
            time.sleep(0.005)

    def close(self, timeout: float = 2.0) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._q.put(None, timeout=timeout)
        except queue.Full:
            pass
        self._worker.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                self._q.task_done()
                break
            try:
                self._sink(item)
                self._delivered += 1
            except Exception:
                pass
            finally:
                self._q.task_done()
