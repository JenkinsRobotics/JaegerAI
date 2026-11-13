"""OpenTelemetry GenAI export of a run (standard: OTel GenAI semantic conventions,
OTLP/JSON encoding). Events are the shapes the Gateway writes (contract.trace)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from jaeger_ai.contract import otel, trace


def _events(rid="req-abc"):
    out = []
    for i, (name, data) in enumerate([
        ("turn.start", {"request_id": rid, "agent_id": "native:jaeger", "display_name": "Jaeger"}),
        ("model.started", {"request_id": rid, "step_id": f"{rid}:1", "model": "grok", "provider": "cli"}),
        ("model.finished", {"request_id": rid, "step_id": f"{rid}:1", "ok": True, "model": "grok", "provider": "cli",
                            "usage": {"prompt_tokens": 120, "completion_tokens": 7}, "cost_usd": 0.01}),
        ("tool.started", {"request_id": rid, "step_id": f"{rid}:1", "call_id": "tool_x_1", "tool": "get_time"}),
        ("tool.failed", {"request_id": rid, "step_id": f"{rid}:1", "call_id": "tool_x_1", "tool": "get_time",
                         "error": "TimeoutError"}),
        ("turn.finish", {"request_id": rid, "status": "completed",
                         "timing": {"usage": {"reported": True, "input_tokens": 120, "output_tokens": 7, "cost_usd": 0.01}}}),
    ]):
        out.append({"event": name, "data": trace.annotate("s1", name, data, ts=1000.0 + i)})
    return out


def test_envelope_carries_a_w3c_trace_id():
    e = _events()[0]["data"]["trace"]
    assert e["trace_id"] == otel.trace_id("req-abc") and len(e["trace_id"]) == 32
    int(e["trace_id"], 16)


def test_spans_follow_genai_conventions_and_nest():
    spans = otel.spans_for_run(_events(), "req-abc", session_id="s1")
    by = {s["name"]: s for s in spans}
    assert set(by) == {"invoke_agent Jaeger", "chat grok", "execute_tool get_time"}
    run, chat, tool = by["invoke_agent Jaeger"], by["chat grok"], by["execute_tool get_time"]
    assert "parentSpanId" not in run
    assert chat["parentSpanId"] == run["spanId"] and tool["parentSpanId"] == chat["spanId"]
    attrs = {a["key"]: a["value"] for a in chat["attributes"]}
    assert attrs["gen_ai.operation.name"] == {"stringValue": "chat"}
    assert attrs["gen_ai.usage.input_tokens"] == {"intValue": "120"}
    assert attrs["gen_ai.request.model"] == {"stringValue": "grok"}
    assert attrs["gen_ai.conversation.id"] == {"stringValue": "s1"}
    assert chat["kind"] == 3 and tool["kind"] == 1
    assert tool["status"]["code"] == 2  # failed tool = ERROR
    assert {a["key"] for a in tool["attributes"]} >= {"gen_ai.tool.name", "gen_ai.tool.call.id", "error.type"}
    assert int(chat["endTimeUnixNano"]) > int(chat["startTimeUnixNano"])
    assert {s["traceId"] for s in spans} == {otel.trace_id("req-abc")}


def test_other_runs_are_not_exported():
    assert otel.spans_for_run(_events("req-other"), "req-abc") == []


def test_push_posts_otlp_json_to_a_collector(monkeypatch):
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            got.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200); self.end_headers()

        def log_message(self, *a):  # noqa: D401
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    doc = otel.otlp_document(otel.spans_for_run(_events(), "req-abc"))
    assert otel.push(doc) == 200
    path, body = got[0]
    assert path == "/v1/traces"
    assert body["resourceSpans"][0]["scopeSpans"][0]["spans"]
    srv.server_close()


def test_push_is_off_without_the_env(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    assert otel.push({"resourceSpans": []}) is None
