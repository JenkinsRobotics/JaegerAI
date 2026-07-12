"""Phase-8 length-truncation retry logic.

Two scenarios the loop must handle gracefully:

  1. Model hits max-tokens mid tool-call JSON → finish_reason="length"
     plus a tool_calls list with truncated args. Retry once silently.
  2. Model hits max-tokens mid prose → finish_reason="length" plus
     plain text. Append the partial, inject a "continue from here"
     nudge, retry up to 3 times, stitch the result.
"""

from __future__ import annotations

from typing import Any

import pytest

from jaeger_ai.agent import (
    JaegerAgent,
    Message,
    ProviderAdapter,
    clear_registry,
)
from jaeger_ai.agent.loop.jaeger_agent import JaegerAgent as _JA


class _ScriptedAdapter(ProviderAdapter):
    """Scripted adapter that returns the next response from a list."""

    name = "scripted"

    def __init__(self, script: list[Message]) -> None:
        self._script = list(script)
        self.call_count = 0
        self.last_messages: list[Message] | None = None

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        self.last_messages = list(messages)
        return {"messages": list(messages)}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.call_count += 1
        if not self._script:
            raise RuntimeError("scripted adapter ran out of responses")
        return self._script.pop(0)

    def parse_response(self, raw):
        return raw  # responses are already Message-shaped

    def supports(self, feature):  # noqa: ARG002
        return False


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


# ── truncated tool call → silent retry ─────────────────────────────


def test_truncated_tool_call_retries_once_silently():
    """First response: tool_calls + finish_reason=length. Loop retries
    silently; second response is a clean text answer."""
    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "broken", "arguments": {"path": "/tmp/x"}},
            ],
            "finish_reason": "length",  # truncated mid-args
        },
        # The retry succeeds cleanly with a text answer.
        {"role": "assistant", "content": "ok done", "finish_reason": "stop"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("do the thing")
    assert result == "ok done"
    # The model was called twice on the same iteration (truncation + retry).
    # Then the loop returned because the second response had no tool calls.
    assert adapter.call_count == 2
    # History contains only the user + the FINAL clean assistant message —
    # the broken truncated response was NOT appended.
    roles = [m["role"] for m in agent.messages]
    assert roles == ["user", "assistant"]
    assert agent.messages[-1]["content"] == "ok done"


def test_double_truncated_tool_call_falls_through():
    """If the second response is STILL truncated (and contains tool
    calls), we stop retrying per the max-retries=1 budget — the
    response reaches the loop where dispatch can surface the unknown-
    tool error and a clean recovery response on the next iteration
    closes the turn."""
    adapter = _ScriptedAdapter([
        # Iteration 1 — initial truncated tool call.
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "name": "broken", "arguments": {}}],
            "finish_reason": "length",
        },
        # Iteration 1 retry #1 — still truncated.
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c2", "name": "broken", "arguments": {}}],
            "finish_reason": "length",
        },
        # Iteration 2 — model sees the unknown-tool result and recovers
        # with a clean answer.
        {"role": "assistant", "content": "couldn't run it", "finish_reason": "stop"},
    ])
    agent = JaegerAgent(adapter=adapter, max_iterations=4)
    result = agent.run_turn("force the loop")
    # Initial call + 1 truncation retry + 1 clean follow-up = 3 calls
    # within the budget. The retry budget for truncated tool calls is
    # exactly 1, so we don't burn the script further.
    assert adapter.call_count == 3
    assert result == "couldn't run it"


# ── truncated text → continuation nudges ───────────────────────────


def test_truncated_text_stitches_with_continuation():
    """Text response gets cut → nudge → next chunk arrives → stitch."""
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "Part one of two: ", "finish_reason": "length"},
        {"role": "assistant", "content": "part two complete.", "finish_reason": "stop"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("write a long thing")
    # The stitched result joins both halves.
    assert "Part one of two: " in result
    assert "part two complete." in result
    assert result == "Part one of two: part two complete."
    # The synthetic nudge turns were trimmed from history — only the
    # user input + the final stitched assistant message remain.
    assert [m["role"] for m in agent.messages] == ["user", "assistant"]


def test_truncated_text_retries_up_to_three_then_returns_partial():
    """Three retries exhausted → return what we have."""
    # Five truncated responses in a row — only the first 4 should be
    # consumed (initial call + 3 retries), then the loop returns the
    # accumulated partial.
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "A", "finish_reason": "length"},
        {"role": "assistant", "content": "B", "finish_reason": "length"},
        {"role": "assistant", "content": "C", "finish_reason": "length"},
        {"role": "assistant", "content": "D", "finish_reason": "length"},
        # This 5th shouldn't be reached — retry budget is 3.
        {"role": "assistant", "content": "should-not-appear", "finish_reason": "stop"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("very long")
    # Initial call + 3 retries = 4 model calls; "D" is the final chunk.
    assert adapter.call_count == 4
    assert result == "ABCD"
    assert "should-not-appear" not in result


def test_clean_response_skips_retry_path_entirely():
    """A non-length finish_reason just returns the message untouched —
    no retry, no nudging."""
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "done", "finish_reason": "stop"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("hi")
    assert result == "done"
    assert adapter.call_count == 1


def test_missing_finish_reason_treated_as_clean():
    """If the adapter didn't surface ``finish_reason`` (e.g., older
    adapter, streaming aggregator), behave as if it was 'stop'."""
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)
    assert agent.run_turn("hi") == "done"
    assert adapter.call_count == 1


# ── retry interacts with tool calls correctly ─────────────────────


def test_retry_does_not_fire_on_normal_tool_call_finish():
    """``finish_reason == "tool_calls"`` is a clean signal — never
    triggers the length-retry path."""
    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "any", "arguments": {}},
            ],
            "finish_reason": "tool_calls",
        },
        {"role": "assistant", "content": "answer", "finish_reason": "stop"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("call tool")
    # No retries — 2 model calls (one for tool dispatch, one for final).
    assert adapter.call_count == 2


# ── constants pinned ───────────────────────────────────────────────


def test_retry_budgets_match_legacy_hermes_constants():
    """The chosen budgets (3 length-continue, 1 tool-call-truncation)
    match the legacy Hermes loop so the benchmark sees the same retry
    behaviour."""
    assert _JA._MAX_LENGTH_CONTINUE_RETRIES == 3
    assert _JA._MAX_TRUNCATED_TOOL_CALL_RETRIES == 1
