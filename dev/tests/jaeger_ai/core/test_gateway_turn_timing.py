"""Receipt timing from an admitted Gateway turn with an isolated fake model."""
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.turn_timing import TurnTiming
from jaeger_ai.core.gateway.turn_audit import is_previous_turn_audit, previous_turn_audit


@pytest.mark.asyncio
async def test_admitted_turn_receipt_has_content_free_timing(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    runtime = SimpleNamespace(
        executive_selector=None, current_state=SimpleNamespace(active_goals=[]),
        identity=SimpleNamespace(entity_id="e", display_name="Jaeger"), layout=None,
        prepare_turn=lambda text, *, session_id, **_: PreparedTurn(
            prompt=text, event=SimpleNamespace(event_id="e1"), user_text=text, session_id=session_id),
        finish_turn=lambda prepared, response_text: None,
    )
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("s")
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    prompt = "private prompt marker J023"
    message = "private message marker J023"
    admitted = app.store.admit_request("s", prompt, request_id="r")
    app._turn_timings["r"] = TurnTiming()

    class FakeModel:
        def run(self, callbacks):
            callbacks.on_model_call_start()
            callbacks.on_stream_delta(message)
            callbacks.on_model_call_done({"prompt_tokens": 7, "completion_tokens": 3})
            for _ in range(8):
                callbacks.on_tool_progress("safe_tool", "start", {})
                callbacks.on_tool_done("safe_tool", {}, {"ok": True}, True, None, 0.0)
            return {"text": "done", "halt_reason": "8 tool calls in a single turn"}

    def owner_react(inner_prompt, **kwargs):
        callbacks, flush = app._turn_stream_callbacks("s", "r")
        return FakeModel().run(callbacks)

    monkeypatch.setattr(app, "_owner_react_turn", owner_react)
    from jaeger_ai.core.runtime import autonomous_runner
    monkeypatch.setattr(autonomous_runner, "run_continued_turn", lambda step, prompt, **_: step(prompt))
    await app._execute_turn("s", admitted["turn_id"], prompt, request_id="r")
    receipt = app.store.get_request("r")["result"]
    timing = receipt["timing"]
    assert timing["model_call_count"] == 1
    assert timing["tool_call_count"] == 8
    assert timing["continuation_step_count"] == 1
    assert timing["halt_reason"] == "8 tool calls in a single turn"
    assert timing["model_calls"][0]["prompt_tokens"] == 7
    assert timing["model_calls"][0]["completion_tokens"] == 3
    assert timing["admission_ms"] <= timing["prepare_turn_start_ms"] <= timing["prepare_turn_end_ms"]
    assert timing["prepare_turn_end_ms"] <= timing["first_model_call_start_ms"] <= timing["first_token_ms"] <= timing["turn_finish_ms"]
    assert all(c["start_ms"] <= c["end_ms"] <= timing["turn_finish_ms"] for c in timing["model_calls"] + timing["tool_calls"])
    assert prompt not in json.dumps(timing)
    assert message not in json.dumps(timing)


def test_turn_usage_totals_tokens_and_cost_across_model_steps():
    from jaeger_ai.core.gateway.turn_timing import TurnTiming
    t = TurnTiming()
    t.model_start(); t.model_done({"prompt_tokens": 100, "completion_tokens": 20, "cost_usd": 0.01})
    t.model_start(); t.model_done({"prompt_tokens": 50, "completion_tokens": 5, "cost_usd": 0.002})
    u = t.snapshot()["usage"]
    assert u == {"requests": 2, "input_tokens": 150, "output_tokens": 25, "total_tokens": 175,
                 "reported": True, "cost_usd": 0.012}
    t2 = TurnTiming(); t2.model_start(); t2.model_done({})
    assert t2.usage()["reported"] is False and t2.usage()["cost_usd"] is None


def test_previous_turn_audit_is_narrow_and_reads_durable_receipt(tmp_path):
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.ensure_session("s")
    store.admit_request("s", "do work", request_id="previous", requested={
        "model": "mistral-large-4:cloud", "provider": "ollama",
    })
    store.complete_request("previous", status="failed", result={
        "error": "Execution stopped at its tool/iteration limit",
        "halt_reason": "made 8 tool calls in a single turn",
        "output": "Partial evidence",
        "timing": {
            "model_call_count": 3, "tool_call_count": 8,
            "continuation_step_count": 1, "turn_finish_ms": 62500,
            "tool_calls": [{"name": "session_list"}, {"name": "session_status"}],
        },
    }, assistant_text="Partial evidence")
    store.admit_request("s", "audit the previous failed request tools steps and time", request_id="current")

    prompt = "Audit the immediately previous failed request: report tools, steps, model, and elapsed time."
    assert is_previous_turn_audit(prompt)
    assert not is_previous_turn_audit("Audit this repository and fix its tools")
    report = previous_turn_audit(store, "s", "current")
    assert "Request ID: previous" in report
    assert "Terminal state: failed" in report
    assert "mistral-large-4:cloud / ollama" in report
    assert "Model calls: 3" in report
    assert "Tool calls: 8" in report
    assert "session_list, session_status" in report
    assert "Continuation/execution steps: 1" in report
    assert "62.500 seconds" in report
    assert "Partial evidence" in report


@pytest.mark.asyncio
async def test_previous_turn_audit_bypasses_model_and_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("s")
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    app.store.admit_request("s", "work", request_id="previous")
    app.store.complete_request("previous", status="failed", result={
        "error": "tool limit", "timing": {"model_call_count": 2, "tool_call_count": 8,
        "continuation_step_count": 1, "turn_finish_ms": 9000, "tool_calls": []},
    })
    audit_text = "Audit the immediately previous failed request and report tools, steps, and elapsed time."
    admitted = app.store.admit_request("s", audit_text, request_id="audit")
    app._turn_timings["audit"] = TurnTiming()
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(
        lambda cls, *a, **k: (_ for _ in ()).throw(AssertionError("model path must not run"))))

    await app._execute_turn("s", admitted["turn_id"], audit_text, request_id="audit")
    receipt = app.store.get_request("audit")
    assert receipt["status"] == "completed"
    assert "Request ID: previous" in receipt["result"]["output"]
    assert receipt["result"]["backend"] == "gateway_receipt_audit"
    assert receipt["result"]["timing"]["model_call_count"] == 0
    assert receipt["result"]["timing"]["tool_call_count"] == 0


@pytest.mark.asyncio
async def test_failed_agent_turn_preserves_partial_text_and_halt_receipt(monkeypatch, tmp_path):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    runtime = SimpleNamespace(
        executive_selector=None, current_state=SimpleNamespace(active_goals=[]),
        identity=SimpleNamespace(entity_id="e", display_name="Jaeger"), layout=None,
        prepare_turn=lambda text, *, session_id, **_: PreparedTurn(
            prompt=text, event=SimpleNamespace(event_id="e1"), user_text=text, session_id=session_id),
        finish_turn=lambda prepared, response_text: None,
    )
    monkeypatch.setattr(EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.store.ensure_session("s")
    monkeypatch.setattr(app, "_resolve_session_agent", lambda sid: None)
    monkeypatch.setattr(app, "_continued_owner_react", lambda *a, **k: {
        "text": "I inspected two receipts before the loop stopped.",
        "error": "Execution stopped at its tool/iteration limit",
        "halt_reason": "made 8 tool calls in a single turn",
        "continuation_steps": 2,
    })
    admitted = app.store.admit_request("s", "inspect the work", request_id="failed")
    app._turn_timings["failed"] = TurnTiming()

    await app._execute_turn("s", admitted["turn_id"], "inspect the work", request_id="failed")
    receipt = app.store.get_request("failed")
    assert receipt["status"] == "failed"
    assert not receipt["result"].get("output")
    assert receipt["result"]["partial_output"] == "I inspected two receipts before the loop stopped."
    assert receipt["result"]["partial"] is True
    assert receipt["result"]["halt_reason"] == "made 8 tool calls in a single turn"
    assert receipt["result"]["continuation_steps"] == 2
    session = app.store.get_session("s")
    assistant = [message for message in session["messages"] if message["role"] == "assistant"][-1]
    assert assistant["content"] == "I inspected two receipts before the loop stopped."
