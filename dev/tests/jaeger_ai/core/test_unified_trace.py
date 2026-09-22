"""Tests for Unified Observability and Provenance Tracing (Workstream 16)."""
from __future__ import annotations

from pathlib import Path
import time

import pytest

from jaeger_ai.core.diagnostics.unified_trace import (
    ExecutionTrace,
    SqliteTraceStore,
    TraceSpan,
)
from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.runtime import EntityRuntime, EntityRuntimeMode


def test_trace_span_lifecycle():
    span = TraceSpan(phase="executive", data={"hint": "deliberate"})
    time.sleep(0.01)
    span.finish(extra_data={"decision": "fast_path"})

    assert span.phase == "executive"
    assert span.ended_at is not None
    assert span.duration_ms > 0
    assert span.data["hint"] == "deliberate"
    assert span.data["decision"] == "fast_path"
    assert span.error is None


def test_execution_trace_and_redaction():
    trace = ExecutionTrace(
        request_id="req_999",
        session_id="session_test",
        actor="operator",
        goal="Configure API key",
    )
    span = trace.start_span("cognition", {"secret_input": "sk-proj-supersecretkey1234567890"})
    span.finish()

    trace.tool_calls.append({
        "tool": "bash",
        "command": "export OPENAI_API_KEY=sk-test-secretvalue-000000000000000000",
    })
    trace.finish(status="success")

    as_dict = trace.to_dict()
    # Check that secrets are redacted
    assert "sk-proj-supersecretkey1234567890" not in str(as_dict)
    assert "sk-test-secretvalue-000000000000000000" not in str(as_dict)
    assert "[REDACTED" in str(as_dict)


def test_sqlite_trace_store_roundtrip(tmp_path: Path):
    db_file = tmp_path / "execution_traces.sqlite3"
    store = SqliteTraceStore(db_file)

    trace = ExecutionTrace(
        request_id="req_abc123",
        session_id="sess_1",
        actor="test_user",
        goal="Run diagnostic",
        model="kimi-k2.7-code:cloud",
        provider="ollama",
        strategy="deliberate",
    )
    s1 = trace.start_span("attention", {"salience": 0.85})
    s1.finish()
    s2 = trace.start_span("cognition")
    s2.finish()
    trace.verification = {"status": "verified", "verifier": "disk_probe", "error": None}
    trace.finish(status="success")

    store.save_trace(trace)

    retrieved = store.get_trace(trace.trace_id)
    assert retrieved is not None
    assert retrieved.trace_id == trace.trace_id
    assert retrieved.request_id == "req_abc123"
    assert retrieved.model == "kimi-k2.7-code:cloud"
    assert retrieved.strategy == "deliberate"
    assert len(retrieved.spans) == 2
    assert retrieved.verification["status"] == "verified"

    # Query by request ID
    by_req = store.get_by_request_id("req_abc123")
    assert by_req is not None
    assert by_req.trace_id == trace.trace_id

    # List traces
    all_traces = store.list_traces(limit=10)
    assert len(all_traces) == 1
    assert all_traces[0].trace_id == trace.trace_id


def test_render_inspection_tree():
    trace = ExecutionTrace(
        request_id="req_tree_test",
        session_id="sess_tree",
        actor="human:operator",
        goal="Investigate disk space",
        model="kimi-k2.7-code:cloud",
        provider="ollama",
        strategy="direct",
    )
    s1 = trace.start_span("attention")
    s1.finish()
    s2 = trace.start_span("cognition")
    s2.finish(error="Timeout connecting to backend")
    trace.finish(status="failed", error="Cognition timed out")

    tree = trace.render_inspection_tree()
    assert "Execution Trace" in tree
    assert "Request ID: req_tree_test" in tree
    assert "[ATTENTION]" in tree
    assert "[COGNITION]" in tree
    assert "Timeout connecting to backend" in tree
    assert "[DIAGNOSTIC FAILURE]: Cognition timed out" in tree


def test_entity_runtime_trace_generation(tmp_path: Path):
    runtime = EntityRuntime(
        state_root=tmp_path / "runtime_state",
        identity=EntityIdentity(
            entity_id="test_agent",
            display_name="TestAgent",
            created_at=time.time(),
            instance_name="test_inst",
        ),
        mode=EntityRuntimeMode.TEST,
    )


    result = runtime.execute_turn(
        "Hello Jaeger, what is your status?",
        session_id="test_session",
        request_id="req_runtime_turn_1",
    )

    assert "trace_id" in result
    trace_id = result["trace_id"]
    assert trace_id

    # Verify trace persisted in the runtime's trace store
    saved_trace = runtime.trace_store.get_trace(trace_id)
    assert saved_trace is not None
    assert saved_trace.request_id == "req_runtime_turn_1"
    assert saved_trace.session_id == "test_session"
    assert saved_trace.status == "success"
    # Spans recorded
    span_phases = [s.phase for s in saved_trace.spans]
    assert "attention" in span_phases
    assert "executive" in span_phases
    assert "cognition" in span_phases
