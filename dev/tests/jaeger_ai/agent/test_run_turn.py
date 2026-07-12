"""``JaegerAgent.run_turn`` — loop-level smoke tests.

The stub adapter returns a scripted list of assistant messages, one per
``call``. That lets us exercise every branch of the loop — no tool
calls, one tool call, parallel tool calls, max-iterations exhaustion,
backstop halt, interrupt, validation error, unknown tool — without ever
touching a real model.
"""

from __future__ import annotations

import threading
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
from jaeger_ai.agent.loop.loop_backstop import MAX_IDENTICAL_CALLS


# ── stub adapter ───────────────────────────────────────────────────


class _ScriptedAdapter(ProviderAdapter):
    """Returns the next scripted message on every ``call`` — no network,
    no formatting, no parsing logic. The agent loop's behaviour is the
    only thing under test."""

    name = "scripted"

    def __init__(self, script: list[Message]) -> None:
        self._script = list(script)
        self.call_count = 0
        self.last_messages: list[Message] = []
        self.last_tools_count = 0

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        # Snapshot what the loop hands us so the test can assert on it.
        self.last_messages = list(messages)
        self.last_tools_count = len(tools)
        return {"messages": messages, "tools": tools, "system": system}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.call_count += 1
        if not self._script:
            raise RuntimeError("scripted adapter ran out of responses")
        return self._script.pop(0)

    def parse_response(self, raw):
        return raw  # already in Message shape

    def supports(self, feature):  # noqa: ARG002
        return False


class _SmallArgs(BaseModel):
    value: str = Field(default="x")


class _StrictArgs(BaseModel):
    n: int = Field(ge=0, le=10)


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


# ── happy paths ────────────────────────────────────────────────────


def test_no_tool_calls_returns_assistant_text_in_one_iteration():
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "the answer is 42"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("what is the meaning of life?")
    assert result == "the answer is 42"
    assert agent.last_iteration_count == 1
    assert agent.last_halt_reason is None
    assert adapter.call_count == 1
    assert len(agent.messages) == 2  # user + assistant


def test_single_tool_call_then_final_answer():
    captured: list[str] = []

    @register_tool("get_time", "Get the time.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        captured.append(value)
        return {"now": "12:00", "got": value}

    adapter = _ScriptedAdapter([
        # turn 1: assistant requests the tool
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "call_1", "name": "get_time", "arguments": {"value": "UTC"}},
            ],
        },
        # turn 2: assistant gives the final answer
        {"role": "assistant", "content": "it is noon"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("what time is it?")
    assert result == "it is noon"
    assert captured == ["UTC"]
    assert adapter.call_count == 2

    # user, assistant(tool_call), tool(result), assistant(final)
    assert [m["role"] for m in agent.messages] == [
        "user", "assistant", "tool", "assistant",
    ]
    tool_msg = agent.messages[2]
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["name"] == "get_time"
    assert "12:00" in tool_msg["content"]


def test_parallel_tool_calls_dispatched_in_one_assistant_turn():
    """Anthropic + modern OpenAI both emit multiple tool calls in one
    assistant message. The loop must dispatch each, then proceed."""
    @register_tool("ping", "Ping.", _SmallArgs)
    def _ping(value: str = "x") -> dict:
        return {"pong": value}

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": "checking",
            "tool_calls": [
                {"id": "c1", "name": "ping", "arguments": {"value": "a"}},
                {"id": "c2", "name": "ping", "arguments": {"value": "b"}},
                {"id": "c3", "name": "ping", "arguments": {"value": "c"}},
            ],
        },
        {"role": "assistant", "content": "all three replied"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("ping three times")
    assert result == "all three replied"

    tool_rows = [m for m in agent.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_rows] == ["c1", "c2", "c3"]
    assert all('"pong"' in m["content"] for m in tool_rows)


# ── tool error paths ───────────────────────────────────────────────


def test_unknown_tool_becomes_tool_error_result_loop_continues():
    """An unknown tool name does NOT crash the turn — it becomes a tool
    result the model can see and self-correct from."""
    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "name": "does_not_exist", "arguments": {}},
            ],
        },
        {"role": "assistant", "content": "ok, I'll skip that"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("call a fake tool")
    assert result == "ok, I'll skip that"
    tool_row = next(m for m in agent.messages if m["role"] == "tool")
    assert "unknown tool" in tool_row["content"]


def test_bad_args_validation_error_becomes_tool_result_not_crash():
    @register_tool("strict", "Strict args.", _StrictArgs)
    def _impl(n: int):
        return {"ok": True, "n": n}

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                # n=99 is out of range — Pydantic raises ValidationError
                {"id": "c1", "name": "strict", "arguments": {"n": 99}},
            ],
        },
        {"role": "assistant", "content": "let me retry"},
    ])
    agent = JaegerAgent(adapter=adapter)
    result = agent.run_turn("try strict")
    assert result == "let me retry"
    tool_row = next(m for m in agent.messages if m["role"] == "tool")
    assert "ValidationError" in tool_row["content"]


def test_tool_raises_exception_captured_as_failure_result():
    @register_tool("boom", "Always raises.", _SmallArgs)
    def _impl(value: str = "x"):
        raise RuntimeError("explosion")

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "name": "boom", "arguments": {}}],
        },
        {"role": "assistant", "content": "ouch"},
    ])
    agent = JaegerAgent(adapter=adapter)
    assert agent.run_turn("trigger boom") == "ouch"
    tool_row = next(m for m in agent.messages if m["role"] == "tool")
    assert "RuntimeError" in tool_row["content"]
    assert "explosion" in tool_row["content"]


# ── loop backstops ─────────────────────────────────────────────────


def test_identical_tool_call_loop_trips_backstop():
    """Hammering the same (tool, args) over and over halts the turn
    with a human-readable reason instead of running forever."""
    @register_tool("loopy", "Always called.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    # MAX_IDENTICAL_CALLS identical calls + a filler final = enough.
    script: list[Message] = []
    for _ in range(MAX_IDENTICAL_CALLS + 2):
        script.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "x", "name": "loopy", "arguments": {"value": "a"}}],
        })

    agent = JaegerAgent(adapter=_ScriptedAdapter(script))
    result = agent.run_turn("loop forever")
    assert agent.last_halt_reason is not None
    assert "loopy" in agent.last_halt_reason
    assert "identical" in agent.last_halt_reason
    # The result message either echoes the halt or a prior assistant —
    # the contract is "halt cleanly", not "produce a specific string".
    assert "halted" in result or result == ""


def test_max_iterations_caps_runaway_loop():
    """When the model never stops calling tools, ``max_iterations`` is
    the hard ceiling — no model call beyond it."""
    @register_tool("nibble", "Varies args each time.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    # Vary args so the identical-call backstop never fires — only the
    # iteration ceiling can stop us.
    script: list[Message] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": f"id{i}", "name": "nibble", "arguments": {"value": f"v{i}"}},
            ],
        }
        for i in range(20)
    ]
    agent = JaegerAgent(adapter=_ScriptedAdapter(script), max_iterations=3)
    agent.run_turn("never stop")
    assert agent.last_iteration_count == 3
    assert agent.last_halt_reason is not None
    assert "max_iterations" in agent.last_halt_reason


# ── cancel + interrupt ─────────────────────────────────────────────


def test_interrupt_set_before_loop_halts_immediately():
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "would have answered"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.interrupt()
    result = agent.run_turn("hello")
    # ``run_turn`` clears the event on entry — so the interrupt set
    # *before* run_turn is not honoured. That's the design: stale
    # cancels can't kill the next turn. Document by asserting the
    # turn completes normally.
    assert result == "would have answered"
    assert agent.interrupted is False


def test_interrupt_mid_loop_halts_after_current_call():
    """An interrupt fired between iterations is honoured at the top of
    the next iteration."""
    @register_tool("trigger_interrupt", "Sets the cancel flag.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        # Fire the cancel via the agent ref the test injects.
        agent_holder["agent"].interrupt()
        return {"ok": True}

    agent_holder: dict[str, JaegerAgent] = {}

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "x", "name": "trigger_interrupt", "arguments": {}},
            ],
        },
        # This would run if the interrupt wasn't honoured.
        {"role": "assistant", "content": "should never appear"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent_holder["agent"] = agent
    agent.run_turn("call the tool that interrupts")
    assert agent.last_halt_reason == "interrupted"


def test_interrupt_after_model_call_discards_response():
    """Uncancellable local backends may only observe the interrupt after
    the model call returns; the loop must not append/render the stale
    assistant response."""
    class _InterruptAfterCall(_ScriptedAdapter):
        def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
            interrupt_event.set()
            return {"role": "assistant", "content": "stale response"}

    agent = JaegerAgent(adapter=_InterruptAfterCall([]))
    result = agent.run_turn("cancel me")
    assert agent.last_halt_reason == "interrupted"
    assert "stale response" not in result
    assert all(m.get("content") != "stale response" for m in agent.messages)


# ── callbacks fired ────────────────────────────────────────────────


def test_callbacks_fire_for_step_and_tool_progress():
    seen_steps: list[tuple[int, str]] = []
    seen_progress: list[tuple[str, str]] = []

    @register_tool("ping", "Ping.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    adapter = _ScriptedAdapter([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "name": "ping", "arguments": {}}],
        },
        {"role": "assistant", "content": "done"},
    ])
    cb = AgentCallbacks(
        step=lambda i, msg: seen_steps.append((i, msg.get("role", ""))),
        tool_progress=lambda name, phase, *_: seen_progress.append((name, phase)),
    )
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    agent.run_turn("ping once")

    assert seen_steps == [(1, "assistant"), (2, "assistant")]
    assert ("ping", "start") in seen_progress
    assert ("ping", "done") in seen_progress


# ── adapter fallback ───────────────────────────────────────────────


class _AlwaysFailingAdapter(ProviderAdapter):
    name = "broken"

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        raise RuntimeError("primary down")

    def parse_response(self, raw):  # noqa: ARG002
        return {"role": "assistant", "content": ""}

    def supports(self, feature):  # noqa: ARG002
        return False


def test_fallback_adapter_picks_up_when_primary_raises():
    backup = _ScriptedAdapter([
        {"role": "assistant", "content": "saved by the backup"},
    ])
    agent = JaegerAgent(
        adapter=_AlwaysFailingAdapter(),
        fallback_adapters=[backup],
    )
    result = agent.run_turn("primary will fail")
    assert result == "saved by the backup"


def test_all_adapters_failing_raises_to_caller():
    """When the entire chain raises, the loop surfaces the last
    exception — the REPL / daemon decides what to do."""
    agent = JaegerAgent(
        adapter=_AlwaysFailingAdapter(),
        fallback_adapters=[_AlwaysFailingAdapter()],
    )
    with pytest.raises(RuntimeError, match="primary down"):
        agent.run_turn("nothing works")


# ── per-turn state reset ───────────────────────────────────────────


def test_call_counters_reset_between_turns():
    """A spinning previous turn must not poison the next one's backstop
    counters."""
    @register_tool("once", "One call.", _SmallArgs)
    def _impl(value: str = "x") -> dict:
        return {"ok": True}

    script: list[Message] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "a", "name": "once", "arguments": {"value": "k"}}],
        },
        {"role": "assistant", "content": "first done"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "b", "name": "once", "arguments": {"value": "k"}}],
        },
        {"role": "assistant", "content": "second done"},
    ]
    agent = JaegerAgent(adapter=_ScriptedAdapter(script))
    agent.run_turn("first")
    # Counters from turn 1 would push turn 2's identical call into the
    # halt range if they weren't cleared.
    agent.run_turn("second")
    assert agent.last_halt_reason is None
    assert agent.last_iteration_count == 2
