"""Phase-5 behaviours: skip-final + before/after tool hooks.

Skip-final short-circuits the loop when a single deterministic tool
answers the turn — the savings are 1-3s per qualifying turn (one model
round-trip avoided). The before/after hooks are the integration seams
for ``core/tool_guardrails`` and ``core/tool_result_budget``; once
Phase 6 migrates ``main.py`` those wires through the new agent loop,
those modules attach here.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_ai.agent import (
    AgentCallbacks,
    JaegerAgent,
    Message,
    ProviderAdapter,
    clear_registry,
    register_tool,
)


class _ScriptedAdapter(ProviderAdapter):
    """Same fixture used by the run_turn tests — a list of canned
    responses, one per ``call``."""

    name = "scripted"

    def __init__(self, script: list[Message]) -> None:
        self._script = list(script)
        self.call_count = 0

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages, "tools": tools, "system": system}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.call_count += 1
        if not self._script:
            raise RuntimeError("scripted adapter ran out of responses")
        return self._script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


class _SmallArgs(BaseModel):
    value: str = Field(default="x")


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


# ── skip-final ──────────────────────────────────────────────────────


def test_skip_final_short_circuits_after_qualifying_tool():
    """One tool call to a skip-final tool on iteration 1 → dispatch,
    finalize, done. Only ONE model call total (the one that issued the
    tool call); the second is skipped."""
    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _impl(value: str = "UTC") -> dict:
        return {"datetime": "12:00", "tz": value}

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "get_time", "arguments": {"value": "UTC"}},
            ],
        },
        # This second response would be used by the full loop — but
        # skip-final must return before it's pulled. Leaving it here
        # asserts the short-circuit didn't happen if the test passes.
        {"role": "assistant", "content": "should not be reached"},
    ])
    agent = JaegerAgent(
        adapter=adapter,
        skip_final_tools={"get_time"},
    )
    result = agent.run_turn("time?")
    assert agent.last_skip_final is True
    assert adapter.call_count == 1  # the finalize step did NOT call the model
    # The default finalizer JSON-encodes the result.
    assert "12:00" in result
    # Transcript: user, assistant(tool_call), tool, assistant(finalizer)
    assert [m["role"] for m in agent.messages] == [
        "user", "assistant", "tool", "assistant",
    ]


def test_skip_final_custom_finalizer_runs():
    """The user-supplied finalizer is called with (tool_name, result,
    user_message) and its return becomes the turn's answer."""
    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"datetime": "noon"}

    seen: dict[str, Any] = {}

    def _finalize(tool_name: str, tool_result: Any, user_message: str) -> str:
        seen["tool_name"] = tool_name
        seen["tool_result"] = tool_result
        seen["user_message"] = user_message
        return "fancy phrased answer"

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "get_time", "arguments": {}},
            ],
        },
    ])
    agent = JaegerAgent(
        adapter=adapter,
        skip_final_tools={"get_time"},
        skip_final_finalizer=_finalize,
    )
    result = agent.run_turn("what time")
    assert result == "fancy phrased answer"
    assert seen["tool_name"] == "get_time"
    assert seen["user_message"] == "what time"
    assert "noon" in seen["tool_result"]


def test_skip_final_does_not_fire_on_parallel_tool_calls():
    """Skip-final requires EXACTLY one tool call. Two parallel calls,
    even to skip-final tools, take the full loop."""
    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"now": "12:00"}

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "a", "name": "get_time", "arguments": {}},
                {"id": "b", "name": "get_time", "arguments": {}},
            ],
        },
        {"role": "assistant", "content": "both done"},
    ])
    agent = JaegerAgent(adapter=adapter, skip_final_tools={"get_time"})
    result = agent.run_turn("time twice")
    assert result == "both done"
    assert agent.last_skip_final is False
    assert adapter.call_count == 2


def test_skip_final_does_not_fire_after_first_iteration():
    """A skip-final tool called LATER in a turn (after non-skip tools)
    runs through the full loop — the savings are only valuable when the
    turn was always going to be a single deterministic tool."""
    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _t(value: str = "x") -> dict:
        return {"now": "12:00"}

    @register_tool("ponder", "Think.", _SmallArgs)
    def _p(value: str = "x") -> dict:
        return {"thought": "hmm"}

    adapter = _ScriptedAdapter([
        # Turn 1: NOT a skip-final tool.
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "p1", "name": "ponder", "arguments": {}}]},
        # Turn 2: now a skip-final tool — but we're past iteration 1.
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "t1", "name": "get_time", "arguments": {}}]},
        {"role": "assistant", "content": "12:00 it is"},
    ])
    agent = JaegerAgent(adapter=adapter, skip_final_tools={"get_time"})
    result = agent.run_turn("ponder then time")
    assert result == "12:00 it is"
    assert agent.last_skip_final is False
    assert adapter.call_count == 3  # full loop ran


def test_skip_final_unset_default_behaviour_unchanged():
    """No ``skip_final_tools`` arg → behaviour identical to Phase 2.
    Existing call sites get zero regressions."""
    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"now": "12:00"}

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "get_time", "arguments": {}}]},
        {"role": "assistant", "content": "it is noon"},
    ])
    agent = JaegerAgent(adapter=adapter)  # no skip_final_tools
    result = agent.run_turn("time?")
    assert result == "it is noon"
    assert agent.last_skip_final is False


def test_skip_final_finalizer_failure_degrades_gracefully():
    """A buggy finalizer shouldn't crash the turn — surface the
    fallback text instead."""
    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"now": "12:00"}

    def _broken(_n, _r, _u):
        raise RuntimeError("finalizer kaboom")

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "get_time", "arguments": {}}]},
    ])
    agent = JaegerAgent(
        adapter=adapter,
        skip_final_tools={"get_time"},
        skip_final_finalizer=_broken,
    )
    result = agent.run_turn("time?")
    assert "finalizer failed" in result
    assert "RuntimeError" in result


# ── before/after tool hooks ────────────────────────────────────────


def test_before_tool_call_hook_injects_guidance():
    """The pre-dispatch hook returns guidance text; it gets attached to
    the tool result as ``loop_guard`` (dict path) or appended (string
    path)."""
    @register_tool("loopy", "Always called.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    def _guard(name: str, args: dict[str, Any]) -> str | None:
        return f"⚠️ called {name}({args}) — please vary your approach"

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "loopy", "arguments": {"value": "x"}}]},
        {"role": "assistant", "content": "ok varied"},
    ])
    cb = AgentCallbacks(before_tool_call=_guard)
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    agent.run_turn("loop me")
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    # Guidance landed inside the result.
    assert "vary your approach" in tool_msg["content"]
    assert "loop_guard" in tool_msg["content"]


def test_before_tool_call_hook_returning_none_is_no_op():
    @register_tool("clean", "Quiet.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True, "value": value}

    def _guard(name: str, args: dict[str, Any]) -> str | None:
        return None  # explicit no-op

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "clean", "arguments": {}}]},
        {"role": "assistant", "content": "done"},
    ])
    cb = AgentCallbacks(before_tool_call=_guard)
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    agent.run_turn("call cleanly")
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    assert "loop_guard" not in tool_msg["content"]


def test_after_tool_call_hook_can_substitute_result():
    """Budget hook substitutes an oversized payload with a pointer.
    Confirm the substitute lands in the appended tool message."""
    @register_tool("big", "Returns lots.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"giant_payload": "x" * 10_000}

    def _budget(name: str, args: dict[str, Any], result: Any) -> Any:
        if isinstance(result, dict) and len(str(result)) > 1000:
            return {"persisted_to": "large_results/abc.json", "truncated": True}
        return None  # leave small results alone

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "big", "arguments": {}}]},
        {"role": "assistant", "content": "noted"},
    ])
    cb = AgentCallbacks(after_tool_call=_budget)
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    agent.run_turn("get the big thing")
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    # The huge payload never reaches the message log.
    assert "x" * 100 not in tool_msg["content"]
    assert "large_results" in tool_msg["content"]


def test_hook_exceptions_swallowed_loop_continues():
    """A buggy hook must NEVER break the turn."""
    @register_tool("t", "T.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    def _broken_before(name, args):
        raise RuntimeError("guardrail bug")

    def _broken_after(name, args, result):
        raise RuntimeError("budget bug")

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "t", "arguments": {}}]},
        {"role": "assistant", "content": "ok"},
    ])
    cb = AgentCallbacks(before_tool_call=_broken_before, after_tool_call=_broken_after)
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    # Should NOT raise.
    result = agent.run_turn("ping")
    assert result == "ok"


def test_after_tool_call_can_return_none_explicitly_via_no_handler():
    """Sanity: when no handler is attached, the loop's behaviour is
    identical to Phase 2 — confirms the new hooks are additive."""
    @register_tool("t", "T.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "c1", "name": "t", "arguments": {}}]},
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)  # default callbacks, no hooks
    agent.run_turn("plain call")
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    assert '"ok": true' in tool_msg["content"]
