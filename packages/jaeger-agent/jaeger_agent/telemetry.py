"""OpenTelemetry GenAI spans for turns and tool calls (optional, local-first).

Follows the OTel GenAI semantic conventions the way Codex and the OpenAI
Agents SDK do: one ``invoke_agent`` span per turn and one ``execute_tool``
span per tool call, with ``gen_ai.*`` attributes. Content (prompts, tool
arguments, outputs) is never recorded, only names, ids and outcomes.

* ``opentelemetry-api`` missing → every helper is a no-op.
* ``opentelemetry-sdk`` present → spans are written as JSON lines to
  ``~/.jaeger/logs/otel-spans.jsonl`` (local only, rotated by logrotate).
* ``OTEL_EXPORTER_OTLP_ENDPOINT`` set and the OTLP exporter installed → also
  exported there. ``JAEGER_OTEL=0`` turns everything off.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_lock = threading.Lock()
_tracer: Any = None
_configured = False


def _spans_path() -> Path:
    root = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger").expanduser()
    path = root / "logs" / "otel-spans.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _configure() -> Any:
    global _tracer, _configured
    with _lock:
        if _configured:
            return _tracer
        _configured = True
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
                        with _spans_path().open("a", encoding="utf-8") as fh:
                            for s in spans:
                                fh.write(json.dumps({
                                    "name": s.name,
                                    "trace_id": f"{s.context.trace_id:032x}",
                                    "span_id": f"{s.context.span_id:016x}",
                                    "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                                    "start_ns": s.start_time, "end_ns": s.end_time,
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
                    except Exception:  # noqa: BLE001 — exporter optional
                        pass
                trace.set_tracer_provider(provider)
        except Exception:  # noqa: BLE001 — no SDK: API-only (no-op unless the host configures one)
            pass
        _tracer = trace.get_tracer("jaeger_agent")
        return _tracer


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a span; yields it (or ``None``). Never raises from telemetry."""
    tracer = _configure()
    if tracer is None:
        yield None
        return
    try:
        cm = tracer.start_as_current_span(name, attributes={k: v for k, v in attributes.items() if v is not None})
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
    return span(f"invoke_agent {agent}", **{
        "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": agent,
        "gen_ai.conversation.id": conversation_id, "jaeger.request_id": request_id, "jaeger.mode": mode,
    })


def tool_span(tool_name: str):
    return span(f"execute_tool {tool_name}", **{
        "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool_name,
    })


def mark(current: Any, **attributes: Any) -> None:
    if current is None:
        return
    try:
        for k, v in attributes.items():
            if v is not None:
                current.set_attribute(k, v)
    except Exception:  # noqa: BLE001
        pass
