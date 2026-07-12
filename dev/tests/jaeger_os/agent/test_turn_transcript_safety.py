"""``JaegerAgent`` transcript invariants on every exit path.

The bug class under test (the VoiceLLM "silent permanent mute" analog):
a turn that bails early — interrupt, backstop halt, adapter exception,
context overflow — used to leave ``self.messages`` in a shape cloud
providers reject (dangling assistant ``tool_calls`` without results,
orphaned user messages, empty assistant text blocks). Because the
broken pair sits at the RECENT end of history, every subsequent turn
in the session then 400s identically until restart.

These tests pin the repaired contract: whatever the exit path,
``self.messages`` must format cleanly on the next turn.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_os.agent import (
    JaegerAgent,
    Message,
    ProviderAdapter,
    clear_registry,
    register_tool,
)
from jaeger_os.agent.util.context_guard import (
    ContextBudget,
    ContextGuard,
    ContextOverflow,
)


class _ScriptedAdapter(ProviderAdapter):
    """Same convention as test_run_turn — scripted Message per call."""

    name = "scripted"

    def __init__(self, script: list[Message | Exception]) -> None:
        self._script = list(script)
        self.call_count = 0

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        self.call_count += 1
        if not self._script:
            raise RuntimeError("scripted adapter ran out of responses")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


class _Args(BaseModel):
    value: str = Field(default="x")


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def _register_echo() -> None:
    @register_tool("echo", "Echo.", _Args)
    def _impl(value: str = "x") -> dict:
        return {"ok": True, "echoed": value}


def _assert_no_dangling_tool_calls(messages: list[Message]) -> None:
    """Every assistant tool_call must have a matching tool result
    before the next non-tool message — the invariant both cloud wire
    formats enforce with a 400."""
    pending: list[str] = []
    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            assert pending, f"orphan tool result: {msg!r}"
            pending.pop(0)
            continue
        assert not pending, f"dangling tool_calls left unanswered: {pending}"
        if role == "assistant":
            pending = [
                tc.get("id") or "?" for tc in (msg.get("tool_calls") or [])
            ]
    assert not pending, f"dangling tool_calls at end of transcript: {pending}"


# ── interrupt mid-dispatch ─────────────────────────────────────────


def test_interrupt_between_tool_dispatches_closes_dangling_calls():
    """Interrupt lands after the assistant message (3 calls) but before
    dispatch finishes — the un-executed calls must get synthetic
    results so the next turn formats cleanly."""
    _register_echo()

    agent_box: dict[str, Any] = {}

    @register_tool("interrupting", "Sets the interrupt as a side effect.", _Args)
    def _interrupting(value: str = "x") -> dict:
        agent_box["agent"].interrupt()
        return {"ok": True}

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "interrupting", "arguments": {}},
            {"id": "c2", "name": "echo", "arguments": {"value": "a"}},
            {"id": "c3", "name": "echo", "arguments": {"value": "b"}},
        ]},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent_box["agent"] = agent
    agent.run_turn("do three things")

    assert agent.last_halt_reason == "interrupted"
    _assert_no_dangling_tool_calls(agent.messages)
    # The synthetic results say why they never ran.
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 3
    assert "not executed" in tool_msgs[1]["content"]
    assert "not executed" in tool_msgs[2]["content"]


def test_backstop_halt_mid_iteration_closes_dangling_calls():
    """The identical-call backstop fires partway through an
    iteration's dispatch list — same repair requirement."""
    _register_echo()
    same_call = {"id": "", "name": "echo", "arguments": {"value": "loop"}}
    # One assistant message per iteration, each hammering the same
    # (tool, args) — plus a trailing un-dispatched call in the final
    # message so the halt leaves it dangling without the repair.
    script: list[Message] = []
    for _ in range(6):
        script.append({
            "role": "assistant", "content": None,
            "tool_calls": [dict(same_call), dict(same_call)],
        })
    adapter = _ScriptedAdapter(script)
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("spin")

    assert agent.last_halt_reason is not None
    assert "identical" in agent.last_halt_reason
    _assert_no_dangling_tool_calls(agent.messages)


# ── adapter failure ────────────────────────────────────────────────


def test_adapter_chain_exhausted_repairs_transcript_and_reraises():
    """All adapters raise → the exception propagates (caller surfaces
    it), but the transcript must carry a failure note instead of an
    orphaned user message that re-poisons every later turn."""
    _register_echo()
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "echo", "arguments": {"value": "a"}},
        ]},
        RuntimeError("backend exploded"),
    ])
    agent = JaegerAgent(adapter=adapter)
    with pytest.raises(RuntimeError, match="backend exploded"):
        agent.run_turn("hello")

    _assert_no_dangling_tool_calls(agent.messages)
    assert agent.last_halt_reason == "error: RuntimeError"
    # Failure note appended as the assistant turn.
    assert agent.messages[-1]["role"] == "assistant"
    assert "turn failed" in agent.messages[-1]["content"]
    # A following turn appends user → roles still alternate sanely.
    roles = [m.get("role") for m in agent.messages]
    assert roles[0] == "user" and roles[-1] == "assistant"


# ── context overflow ───────────────────────────────────────────────


def test_preflight_overflow_rolls_back_user_message_and_raises():
    """Overflow before anything reached the model: the user message
    must NOT stay in history (it would re-trip the guard on every
    subsequent turn) and the typed error propagates for the caller's
    friendly rendering."""
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "never reached"},
    ])
    # Budget so small even the system prompt overflows.
    guard = ContextGuard(ContextBudget(
        ctx_window=64, reserve_for_completion=32, safety_margin=16,
    ))
    agent = JaegerAgent(
        adapter=adapter,
        system_prompt="words " * 200,
        context_guard=guard,
    )
    before = list(agent.messages)
    with pytest.raises(ContextOverflow):
        agent.run_turn("hi")
    assert agent.messages == before
    assert agent.last_turn_messages == []


def test_midturn_overflow_halts_cleanly_instead_of_raising():
    """Overflow on the SECOND model step (in-flight turn too big to
    trim): the turn must end with a spoken-able explanation and a
    well-formed transcript, not a backtrace."""
    _register_echo()

    class _OverflowingGuard(ContextGuard):
        def __init__(self) -> None:
            super().__init__(ContextBudget(ctx_window=8192))
            self.calls = 0

        def trim_to_fit(self, messages, *, system_prompt, tools):
            self.calls += 1
            if self.calls >= 2:
                raise ContextOverflow(
                    estimated=9999, budget=100,
                    system_prompt_tokens=10, tools_tokens=10,
                    latest_user_tokens=10,
                )
            return super().trim_to_fit(
                messages, system_prompt=system_prompt, tools=tools,
            )

    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "echo", "arguments": {"value": "a"}},
        ]},
        {"role": "assistant", "content": "never reached"},
    ])
    agent = JaegerAgent(adapter=adapter, context_guard=_OverflowingGuard())
    answer = agent.run_turn("do a thing")

    assert agent.last_halt_reason == "context_overflow"
    assert "context window" in answer
    _assert_no_dangling_tool_calls(agent.messages)
    assert agent.messages[-1]["role"] == "assistant"


# ── empty response ─────────────────────────────────────────────────


def test_empty_assistant_response_stores_placeholder_not_empty():
    """content=None + no tool calls must not append an empty assistant
    message (Anthropic rejects empty text blocks on every LATER call).
    The caller gets '' back; history carries a placeholder."""
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None},
    ])
    agent = JaegerAgent(adapter=adapter)
    answer = agent.run_turn("hello?")
    assert answer == ""
    assert agent.last_halt_reason == "empty_response"
    last = agent.messages[-1]
    assert last["role"] == "assistant"
    assert last["content"]  # non-empty placeholder


# ── halt text scoping ──────────────────────────────────────────────


def test_interrupted_turn_does_not_resurface_previous_turns_answer():
    """A turn interrupted before its first model response must NOT
    return the PREVIOUS turn's text — the voice loop would speak the
    old answer again."""

    class _InterruptingAdapter(_ScriptedAdapter):
        """Simulates a cancel landing while the model call is in
        flight — exactly what ``interruptible_call`` produces."""

        def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
            from jaeger_os.agent.loop.interrupt import AgentInterrupted
            interrupt_event.set()
            raise AgentInterrupted("cancelled")

    agent = JaegerAgent(adapter=_InterruptingAdapter([]))
    agent.messages = [
        {"role": "user", "content": "old q"},
        {"role": "assistant", "content": "OLD ANSWER"},
    ]
    out = agent.run_turn("new question")
    assert "OLD ANSWER" not in out
    assert agent.last_halt_reason == "interrupted"


# ── per-turn slice bookkeeping ─────────────────────────────────────


def test_last_turn_messages_survives_midturn_history_trim():
    """The context guard rebinding ``agent.messages`` to a trimmed copy
    mid-turn must not corrupt the per-turn slice the bridge persists."""
    _register_echo()
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "echo", "arguments": {"value": "a"}},
        ]},
        {"role": "assistant", "content": "done"},
    ])
    # Small-but-workable budget: old turns get trimmed, current stays.
    guard = ContextGuard(ContextBudget(
        ctx_window=700, reserve_for_completion=64, safety_margin=16,
    ))
    agent = JaegerAgent(adapter=adapter, context_guard=guard)
    # Pre-seed bulky old history so the trim fires mid-turn.
    for i in range(12):
        agent.messages.append({"role": "user", "content": f"old q {i} " + "pad " * 40})
        agent.messages.append({"role": "assistant", "content": f"old a {i} " + "pad " * 40})

    answer = agent.run_turn("run echo then finish")
    assert answer == "done"
    turn = agent.last_turn_messages
    roles = [m.get("role") for m in turn]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert turn[0]["content"] == "run echo then finish"
    assert turn[-1]["content"] == "done"
    # Every turn message is still IN the (possibly rebound) history.
    for m in turn:
        assert m in agent.messages


# ── beta tool gating ───────────────────────────────────────────────


def _register_beta_pair() -> None:
    @register_tool("stable_echo", "Stable echo.", _Args)
    def _stable(value: str = "x") -> dict:
        return {"ok": True, "echoed": value}

    @register_tool("beta_avatar", "Half-tested avatar tool.", _Args, beta=True)
    def _beta(value: str = "x") -> dict:
        return {"ok": True, "avatar": value}


def test_beta_tool_hidden_and_undispatchable_outside_dev_mode(monkeypatch):
    """Without JAEGER_DEV_MODE, a beta tool is neither in the model's
    schema view nor dispatchable — the model can't break the session
    with a half-tested tool even if it hallucinates the name."""
    monkeypatch.delenv("JAEGER_DEV_MODE", raising=False)
    _register_beta_pair()
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "beta_avatar", "arguments": {"value": "wave"}},
        ]},
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)

    names = [t.name for t in agent.tools]
    assert "stable_echo" in names
    assert "beta_avatar" not in names

    agent.run_turn("wave")
    # The dispatch refused it as unknown — surfaced to the model as a
    # self-correctable error, not a crash.
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "unknown tool" in tool_msgs[0]["content"]


def test_beta_tool_available_in_dev_mode(monkeypatch):
    monkeypatch.setenv("JAEGER_DEV_MODE", "1")
    _register_beta_pair()
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "beta_avatar", "arguments": {"value": "wave"}},
        ]},
        {"role": "assistant", "content": "done"},
    ])
    agent = JaegerAgent(adapter=adapter)

    assert "beta_avatar" in [t.name for t in agent.tools]
    answer = agent.run_turn("wave")
    assert answer == "done"
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert "avatar" in tool_msgs[0]["content"]


def test_dev_mode_flip_takes_effect_next_turn_without_rebuild(monkeypatch):
    """The gate re-evaluates per turn (catalogue refresh), so toggling
    JAEGER_DEV_MODE on a long-lived agent works without a rebuild."""
    monkeypatch.delenv("JAEGER_DEV_MODE", raising=False)
    _register_beta_pair()
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "turn 1"},
        {"role": "assistant", "content": "turn 2"},
    ])
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("hi")
    assert "beta_avatar" not in [t.name for t in agent.tools]

    monkeypatch.setenv("JAEGER_DEV_MODE", "1")
    agent.run_turn("hi again")
    assert "beta_avatar" in [t.name for t in agent.tools]


def test_explicit_tools_list_bypasses_beta_gate(monkeypatch):
    """A caller that hands the agent explicit ToolDefs picked them
    deliberately — the beta gate must not second-guess an allowlist."""
    monkeypatch.delenv("JAEGER_DEV_MODE", raising=False)
    _register_beta_pair()
    from jaeger_os.core.tools.tool_registry import get_tool
    beta_def = get_tool("beta_avatar")
    adapter = _ScriptedAdapter([
        {"role": "assistant", "content": "ok"},
    ])
    agent = JaegerAgent(adapter=adapter, tools=[beta_def])
    assert [t.name for t in agent.tools] == ["beta_avatar"]
