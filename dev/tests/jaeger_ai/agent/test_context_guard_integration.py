"""End-to-end: a turn driven through ``drive_one_turn`` with a tiny
context budget returns a friendly overflow message instead of
exploding.

The unit tests in ``test_context_guard.py`` pin the module's internal
shape. This file exercises the full path the TUI sees:

  user_text → JaegerAgent.run_turn → ContextGuard.trim_to_fit
            → ContextOverflow raised → drive_one_turn catches
            → returns ``answer`` with the friendly text +
              ``halt_reason="context_overflow"``

So when the bug from the user's session ("Requested tokens (16628)
exceed context window of 16384") happens again, the operator gets a
proactive, actionable message — never the raw server 400.
"""

from __future__ import annotations

from jaeger_ai.agent.adapters.base import ProviderAdapter
from jaeger_ai.agent.loop.jaeger_agent import JaegerAgent
from jaeger_ai.agent.loop.runtime_bridge import drive_one_turn
from jaeger_ai.agent.util.context_guard import ContextBudget, ContextGuard


class _NeverCalledAdapter(ProviderAdapter):
    """Adapter that fails the test if the loop actually invokes it.
    The overflow guard must fire *before* this adapter is reached."""

    def describe(self) -> str:
        return "never-called"

    def format_messages(self, *_a, **_kw):
        raise AssertionError(
            "format_messages must not be reached when the guard refuses",
        )

    def call(self, *_a, **_kw):
        raise AssertionError("call must not be reached when the guard refuses")

    def parse_response(self, *_a, **_kw):
        raise AssertionError(
            "parse_response must not be reached when the guard refuses",
        )

    def supports(self, *_a, **_kw) -> bool:
        return False


def test_drive_one_turn_returns_friendly_text_on_overflow():
    """Build an agent with a deliberately tiny budget, send a long user
    message, and check that ``drive_one_turn`` returns a friendly
    answer (never reaching the adapter) with the right halt reason."""
    # Budget so small that any non-trivial user message can't fit.
    guard = ContextGuard(ContextBudget(
        ctx_window=20,
        reserve_for_completion=0,
        safety_margin=0,
        chars_per_token=1.0,
    ))
    agent = JaegerAgent(
        adapter=_NeverCalledAdapter(),
        system_prompt="x" * 50,    # already over the 20-tok budget
        tools=[],
        context_guard=guard,
    )

    out = drive_one_turn(agent, "tell me about the weather")

    assert out["halt_reason"] == "context_overflow"
    assert out["iterations"] == 0
    # The friendly text explains the budget breakdown.
    answer = out["answer"]
    assert "Refused to send" in answer or "context budget" in answer
    assert "config.model.ctx" in answer
    # The numbers from the exception should appear in the message.
    assert "budget" in answer.lower()
    # And the turn's tool_activity is empty (nothing happened).
    assert out["tool_activity"] == []
    assert out["new_messages"] == []


def test_drive_one_turn_succeeds_when_prompt_fits():
    """The opposite of the above — a roomy budget, a tiny prompt, and
    the guard stays out of the way. This pins that we don't accidentally
    short-circuit a perfectly-good turn."""
    from jaeger_ai.agent.schemas.message_types import Message

    class _OneAnswerAdapter(ProviderAdapter):
        def describe(self) -> str:
            return "one-answer"

        def format_messages(self, *_a, **_kw):
            return ("formatted", )

        def call(self, *_a, **_kw):
            return "raw"

        def parse_response(self, _raw) -> Message:
            return {"role": "assistant", "content": "hello back"}

        def supports(self, *_a, **_kw) -> bool:
            return False

    guard = ContextGuard(ContextBudget(ctx_window=10_000))
    agent = JaegerAgent(
        adapter=_OneAnswerAdapter(),
        system_prompt="be helpful",
        tools=[],
        context_guard=guard,
    )

    out = drive_one_turn(agent, "hi")
    assert out["halt_reason"] is None
    assert out["answer"] == "hello back"
