"""OpenTelemetry GenAI view of one Jaeger run (OTLP/JSON spans).

Standard followed: OpenTelemetry semantic conventions for generative AI
(``gen_ai.*`` attributes; span names ``invoke_agent {agent}``, ``chat {model}``,
``execute_tool {tool}``) and the OTLP/JSON trace encoding, so any OTel backend
(Jaeger tracing, Tempo, Honeycomb, Langfuse, Phoenix) can ingest a Jaeger turn
without a custom adapter.

The span tree is the one :mod:`jaeger_ai.contract.trace` already writes on
every event (``run_id`` / ``span_id`` / ``parent_span_id``); this module only
re-encodes it. Ids are W3C-sized and deterministic: ``trace_id`` = 16 bytes and
``span_id`` = 8 bytes of SHA-256 over the Jaeger ids, so the same run always
exports the same trace. No prompt or tool content is exported, only names,
ids, timings, usage and status.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import Any, Iterable

_OPERATION = {"run": "invoke_agent", "subagent": "invoke_agent", "model": "chat", "tool": "execute_tool"}
_EXPORTED_KINDS = frozenset(_OPERATION) | {"approval"}


def trace_id(run_id: str) -> str:
    return hashlib.sha256(f"jaeger-trace:{run_id}".encode()).hexdigest()[:32]


def span_id(run_id: str, jaeger_span: str) -> str:
    return hashlib.sha256(f"jaeger-span:{run_id}:{jaeger_span}".encode()).hexdigest()[:16]


def _attr(key: str, value: Any) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)[:256]}}


def _ns(ts: float | None) -> str:
    return str(int(float(ts or 0) * 1_000_000_000))


def spans_for_run(events: Iterable[dict[str, Any]], run_id: str, *, session_id: str = "") -> list[dict[str, Any]]:
    """OTLP span dicts for one run from stored/live event records."""
    spans: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in events:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        trace = record.get("trace") if isinstance(record.get("trace"), dict) else data.get("trace")
        if not isinstance(trace, dict) or trace.get("run_id") != run_id:
            continue
        kind, key = trace.get("kind"), trace.get("span_id")
        if kind not in _EXPORTED_KINDS or not key:
            continue
        ts = float(trace.get("ts") or record.get("timestamp") or 0)
        span = spans.get(key)
        if span is None:
            span = spans[key] = {"key": key, "kind": kind, "name": trace.get("name") or kind,
                                 "parent": trace.get("parent_span_id"), "start": ts, "end": ts,
                                 "state": trace.get("state"), "attrs": {}}
            order.append(key)
        span["end"] = max(span["end"], ts)
        if trace.get("state"):
            span["state"] = trace["state"]
        a = span["attrs"]
        event = record.get("event") or data.get("event")
        if kind == "model":
            a["gen_ai.request.model"] = data.get("model") or a.get("gen_ai.request.model")
            a["gen_ai.provider.name"] = data.get("provider") or a.get("gen_ai.provider.name")
            if data.get("actual_model"):
                a["gen_ai.response.model"] = data["actual_model"]
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            if usage.get("prompt_tokens") is not None:
                a["gen_ai.usage.input_tokens"] = int(usage["prompt_tokens"])
            if usage.get("completion_tokens") is not None:
                a["gen_ai.usage.output_tokens"] = int(usage["completion_tokens"])
            if isinstance(data.get("cost_usd"), (int, float)):
                a["jaeger.cost_usd"] = float(data["cost_usd"])
            if data.get("error"):
                a["error.type"] = data["error"]
        elif kind == "tool":
            a["gen_ai.tool.name"] = data.get("tool") or span["name"]
            a["gen_ai.tool.call.id"] = data.get("call_id") or data.get("activity_id")
            if event in ("tool.failed", "tool.error") and (data.get("error") or data.get("outcome")):
                a["error.type"] = str(data.get("error") or data.get("outcome"))[:120]
        elif kind in ("run", "subagent"):
            a["gen_ai.agent.name"] = data.get("display_name") or data.get("agent_name") or a.get("gen_ai.agent.name")
            a["gen_ai.agent.id"] = data.get("agent_id") or a.get("gen_ai.agent.id")
            if event == "turn.finish" and isinstance((data.get("timing") or {}).get("usage"), dict):
                u = data["timing"]["usage"]
                if u.get("reported"):
                    a["gen_ai.usage.input_tokens"] = u.get("input_tokens")
                    a["gen_ai.usage.output_tokens"] = u.get("output_tokens")
                if isinstance(u.get("cost_usd"), (int, float)):
                    a["jaeger.cost_usd"] = float(u["cost_usd"])
    tid = trace_id(run_id)
    out = []
    for key in order:
        s = spans[key]
        op = _OPERATION.get(s["kind"], "jaeger." + s["kind"])
        attrs = {"gen_ai.operation.name": op, "gen_ai.conversation.id": session_id or None,
                 "jaeger.run_id": run_id, "jaeger.span_id": key, **s["attrs"]}
        label = attrs.get("gen_ai.request.model") or attrs.get("gen_ai.tool.name") or attrs.get("gen_ai.agent.name") or s["name"]
        failed = s["state"] in ("failed", "denied", "unknown")
        span = {
            "traceId": tid, "spanId": span_id(run_id, key),
            "name": f"{op} {label}".strip() if s["kind"] in _OPERATION else f"{s['kind']} {s['name']}",
            "kind": 3 if s["kind"] == "model" else 1,  # SpanKind CLIENT for the model call, else INTERNAL
            "startTimeUnixNano": _ns(s["start"]), "endTimeUnixNano": _ns(s["end"]),
            "attributes": [x for k, v in attrs.items() if (x := _attr(k, v))],
            "status": {"code": 2 if failed else (1 if s["state"] in ("succeeded", "cancelled") else 0),
                       **({"message": s["state"]} if failed or s["state"] == "cancelled" else {})},
        }
        if s["parent"] and s["parent"] in spans:
            span["parentSpanId"] = span_id(run_id, s["parent"])
        out.append(span)
    return out


def otlp_document(spans: list[dict[str, Any]], *, service: str = "jaeger") -> dict[str, Any]:
    return {"resourceSpans": [{
        "resource": {"attributes": [_attr("service.name", service)]},
        "scopeSpans": [{"scope": {"name": "jaeger_ai.contract.trace", "version": "1"}, "spans": spans}],
    }]}


def export_endpoint() -> str:
    """Standard OTel env vars: ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`` or
    ``OTEL_EXPORTER_OTLP_ENDPOINT`` + ``/v1/traces`` (OTLP/HTTP JSON)."""
    direct = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if direct:
        return direct
    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
    return f"{base}/v1/traces" if base else ""


def push(document: dict[str, Any], endpoint: str | None = None, timeout: float = 5.0) -> int | None:
    """POST an OTLP/JSON document; returns the HTTP status (None when not configured)."""
    url = endpoint if endpoint is not None else export_endpoint()
    if not url:
        return None
    req = urllib.request.Request(url, data=json.dumps(document).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-configured URL
        return int(resp.status)
