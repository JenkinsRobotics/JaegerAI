"""Regression tests for user-visible external delegate replies."""

from jaeger_ai.main import _format_tool_result_as_answer


def test_external_delegate_summary_is_rendered_as_answer() -> None:
    result = {
        "delegated": True,
        "runtime": "codex",
        "task_id": "delegate-1",
        "summary": "JAEGER-DELEGATION-ACK",
    }

    assert _format_tool_result_as_answer("delegate_task", result) == "JAEGER-DELEGATION-ACK"


def test_internal_delegate_answer_still_takes_precedence() -> None:
    result = {
        "delegated": True,
        "answer": "internal answer",
        "summary": "external summary",
    }

    assert _format_tool_result_as_answer("delegate_task", result) == "internal answer"
