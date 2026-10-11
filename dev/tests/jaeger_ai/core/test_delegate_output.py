"""Regression tests for user-visible external delegate replies."""

from jaeger_ai.main import _format_tool_result_as_answer
from jaeger_agent.tools.delegation import CAPABILITY_SUMMARY


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


def test_runtime_capability_summary_names_computer_and_external_agent_tools() -> None:
    assert "computer_look" in CAPABILITY_SUMMARY
    assert "computer_do / computer_use" in CAPABILITY_SUMMARY
    assert "runtime=codex|claude|gemini" in CAPABILITY_SUMMARY
