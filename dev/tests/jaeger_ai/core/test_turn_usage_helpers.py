"""Run usage includes inner helpers; OTel exports usage on every terminal run."""
from jaeger_ai.contract import otel
from jaeger_ai.core.gateway.turn_timing import TurnTiming


def test_helper_usage_rolls_up_once():
    t = TurnTiming()
    t.model_start(); t.model_done({"prompt_tokens": 100, "completion_tokens": 20, "cost_usd": 0.01})
    t.helper_done("h1", {"prompt": 50, "completion": 5, "cost_usd": 0.002, "reported": True}, "completed")
    t.helper_done("h1", {"prompt": 50, "completion": 5}, "completed")  # duplicate ignored
    u = t.usage()
    assert u["total_tokens"] == 120
    assert u["helpers"]["count"] == 1 and u["helpers"]["total_tokens"] == 55
    assert u["total_with_helpers"]["total_tokens"] == 175
    assert abs(u["total_with_helpers"]["cost_usd"] - 0.012) < 1e-9


def test_cancelled_run_exports_usage_and_error():
    run = "req_1"
    events = [
        {"event": "turn.start", "data": {"request_id": run},
         "trace": {"run_id": run, "kind": "run", "span_id": f"run:{run}", "ts": 1.0, "state": "running"}},
        {"event": "turn.cancelled", "data": {"request_id": run, "error": "cancelled by Global Stop",
                                             "timing": {"usage": {"reported": True, "input_tokens": 7,
                                                                  "output_tokens": 3, "cost_usd": 0.001}}},
         "trace": {"run_id": run, "kind": "run", "span_id": f"run:{run}", "ts": 2.0, "state": "cancelled"}},
    ]
    spans = otel.spans_for_run(events, run)
    attrs = {a["key"]: a["value"] for a in spans[0]["attributes"]}
    assert attrs["gen_ai.usage.input_tokens"] == {"intValue": "7"}
    assert "error.type" in attrs
