from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "qualify_live_turn.py"
    spec = importlib.util.spec_from_file_location("qualify_live_turn", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_evaluator_reads_structured_receipt_without_model_self_audit():
    observed, failures = _module().evaluate_receipt(
        {
            "status": "completed",
            "result": {
                "output": "A=0.13.0 B=1.2.0",
                "timing": {
                    "model_call_count": 2,
                    "continuation_step_count": 1,
                    "tool_calls": [
                        {"name": "read_file"}, {"name": "read_file"}, {"name": "read_file"},
                    ],
                },
            },
        },
        expect_status="completed", expect_output=["0.13.0", "1.2.0"],
        expect_tools=["read_file", "read_file", "read_file"],
        max_model_calls=2, max_steps=1,
    )
    assert failures == []
    assert observed["tools"] == ["read_file", "read_file", "read_file"]


def test_evaluator_reports_exact_contract_failures():
    _, failures = _module().evaluate_receipt(
        {"status": "failed", "result": {"output": "partial", "timing": {}}},
        expect_status="completed", expect_output=["required"], expect_tools=[],
        max_model_calls=1, max_steps=1,
    )
    assert failures == [
        "status 'failed' != 'completed'", "output missing 'required'",
        "model_call_count None exceeds 1", "continuation_step_count None exceeds 1",
    ]
