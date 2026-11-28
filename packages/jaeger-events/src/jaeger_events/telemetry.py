"""Non-blocking background telemetry queue + W3C traceparent helpers.

Harvested from:
- hermes-agent (`monitoring/emitter.py`): bounded non-blocking queue that drops
  telemetry rather than ever stalling the agent turn loop.
- goose (`otel/trace_context.rs`): W3C `traceparent` header generation and
  parsing for propagating trace context across MCP/A2A tool boundaries.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping


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


# ── Local-first OpenTelemetry GenAI spans (optional, zero-cost when absent) ─

_otel_lock = threading.Lock()
_otel_tracer: Any = None
_otel_configured = False


def _otel_spans_path() -> Path:
    root = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger").expanduser()
    path = root / "logs" / "otel-spans.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _configure_otel() -> Any:
    global _otel_tracer, _otel_configured
    with _otel_lock:
        if _otel_configured:
            return _otel_tracer
        _otel_configured = True
        if os.environ.get("JAEGER_OTEL", "1").strip().lower() in {"0", "false", "no", "off"}:
            return None
        try:
            from opentelemetry import trace
        except Exception:  # noqa: BLE001 — API not installed: no-op
            return None
        try:
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

            class _JsonlExporter(SpanExporter):
                def export(self, spans):  # type: ignore[override]
                    try:
                        with _otel_spans_path().open("a", encoding="utf-8") as fh:
                            for s in spans:
                                fh.write(json.dumps({
                                    "name": s.name,
                                    "trace_id": f"{s.context.trace_id:032x}",
                                    "span_id": f"{s.context.span_id:016x}",
                                    "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                                    "start_ns": s.start_time,
                                    "end_ns": s.end_time,
                                    "duration_ms": round(((s.end_time or 0) - (s.start_time or 0)) / 1e6, 1),
                                    "status": s.status.status_code.name,
                                    "attributes": dict(s.attributes or {}),
                                }) + "\n")
                    except OSError:
                        return SpanExportResult.FAILURE
                    return SpanExportResult.SUCCESS

            current = trace.get_tracer_provider()
            if not isinstance(current, TracerProvider):
                provider = TracerProvider(resource=Resource.create({"service.name": "jaeger"}))
                provider.add_span_processor(SimpleSpanProcessor(_JsonlExporter()))
                if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
                    try:
                        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                        from opentelemetry.sdk.trace.export import BatchSpanProcessor
                        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
                    except Exception:  # noqa: BLE001
                        pass
                trace.set_tracer_provider(provider)
        except Exception:  # noqa: BLE001
            pass
        _otel_tracer = trace.get_tracer("jaeger_events")
        return _otel_tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start an OTel span; yields it (or ``None``). Never raises from telemetry."""
    tracer = _configure_otel()
    if tracer is None:
        yield None
        return
    try:
        cm = tracer.start_as_current_span(
            name, attributes={k: v for k, v in attributes.items() if v is not None},
        )
        current = cm.__enter__()
    except Exception:  # noqa: BLE001
        yield None
        return
    exc_info: tuple = (None, None, None)
    try:
        yield current
    except BaseException as exc:
        exc_info = (type(exc), exc, exc.__traceback__)
        try:
            from opentelemetry.trace import Status, StatusCode
            current.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        try:
            cm.__exit__(*exc_info)
        except Exception:  # noqa: BLE001
            pass


def agent_span(agent: str, conversation_id: str | None, request_id: str | None, mode: str | None = None):
    return span(
        f"invoke_agent {agent}",
        **{
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": agent,
            "gen_ai.conversation.id": conversation_id,
            "jaeger.request_id": request_id,
            "jaeger.mode": mode,
        },
    )


def tool_span(tool_name: str):
    return span(
        f"execute_tool {tool_name}",
        **{
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool_name,
        },
    )


def mark(current: Any, **attributes: Any) -> None:
    if current is None:
        return
    try:
        for k, v in attributes.items():
            if v is not None:
                current.set_attribute(k, v)
    except Exception:  # noqa: BLE001
        pass
