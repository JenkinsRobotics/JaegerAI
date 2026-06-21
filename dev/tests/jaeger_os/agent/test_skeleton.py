"""Phase-1 smoke tests for the JROS agent layer.

What this file pins:

  • the public ``jaeger_os.agent`` surface imports cleanly
  • ``Message`` / ``ToolCall`` TypedDicts construct as dicts
  • a tool registers, looks up, dispatches, and renders three ways
  • runtime registration (the skills + MCP path) works alongside the decorator
  • ``JaegerAgent`` constructs against the adapter ABC and exposes the
    full Phase-1 public surface
  • the interrupt event sets and clears cleanly

No LLM calls. No live HTTP. No real adapter implementation. Phase 2+
fills in behaviour against these contracts.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_os.agent import (
    AgentCallbacks,
    AgentInterrupted,
    JaegerAgent,
    Message,
    ProviderAdapter,
    ToolCall,
    ToolDef,
    clear_registry,
    get_tool,
    get_tools,
    has_tool,
    interruptible_call,
    register_tool,
    register_tool_instance,
    unregister_tool,
)


# ── Test fixtures ────────────────────────────────────────────────────


class _GetTimeArgs(BaseModel):
    timezone: str = Field(default="UTC")


class _MoveJointArgs(BaseModel):
    joint_id: int = Field(ge=0, le=23)
    target_angle_rad: float = Field(ge=-3.14159, le=3.14159)


class _NoOpAdapter(ProviderAdapter):
    """Minimal adapter that does not call any model — exercises the
    ABC contract without network or LLM."""

    name = "noop"

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages, "tools": tools, "system": system}

    def call(self, formatted, interrupt_event, **kwargs):  # noqa: ARG002
        return {"role": "assistant", "content": "(noop)"}

    def parse_response(self, raw):
        return raw  # already in Message shape

    def supports(self, feature):  # noqa: ARG002
        return False


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Every test gets a clean registry. Hermes-agent does the same in
    its test suite to keep cases independent."""
    clear_registry()
    yield
    clear_registry()


# ── Message / ToolCall TypedDicts ────────────────────────────────────


def test_message_typeddict_constructs_as_plain_dict():
    msg: Message = {"role": "user", "content": "hello"}
    assert msg["role"] == "user"
    assert msg["content"] == "hello"


def test_tool_call_typeddict_constructs_as_plain_dict():
    tc: ToolCall = {"id": "call_1", "name": "get_time", "arguments": {"timezone": "UTC"}}
    assert tc["name"] == "get_time"
    assert tc["arguments"] == {"timezone": "UTC"}


def test_assistant_message_carries_tool_calls():
    msg: Message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "1", "name": "get_time", "arguments": {}}],
    }
    assert msg["role"] == "assistant"
    assert msg["tool_calls"] is not None
    assert msg["tool_calls"][0]["name"] == "get_time"


# ── Tool registry round-trip ─────────────────────────────────────────


def test_register_tool_decorator_makes_tool_discoverable():
    @register_tool(
        name="get_time",
        description="Get the current time.",
        args_model=_GetTimeArgs,
    )
    def _impl(timezone: str = "UTC") -> dict:
        return {"time": "12:00", "timezone": timezone}

    assert has_tool("get_time")
    tool = get_tool("get_time")
    assert tool.name == "get_time"
    assert tool.description == "Get the current time."
    assert tool.args_model is _GetTimeArgs


def test_runtime_registration_path_for_skills_and_mcp():
    """The skill loader + MCP bridge can't use the decorator — they
    build ToolDefs at runtime and register them. That path must work
    identically to the decorator."""

    def _impl(joint_id: int, target_angle_rad: float) -> dict:
        return {"ok": True, "joint_id": joint_id}

    tool_def = ToolDef(
        name="move_joint",
        description="Move one joint.",
        args_model=_MoveJointArgs,
        fn=_impl,
        dangerous=True,    # hardware tools opt into safety review
    )
    register_tool_instance(tool_def)

    assert has_tool("move_joint")
    fetched = get_tool("move_joint")
    assert fetched is tool_def
    assert fetched.dangerous is True


def test_unregister_tool_drops_it():
    @register_tool("temp", "Temp tool.", _GetTimeArgs)
    def _impl(timezone: str = "UTC") -> dict:
        return {}

    assert has_tool("temp")
    unregister_tool("temp")
    assert not has_tool("temp")


def test_get_tools_returns_a_fresh_list():
    """Callers mutate the list (toolset filtering, sorting) — the
    registry must hand back a copy, not its live storage."""

    @register_tool("a", "", _GetTimeArgs)
    def _a():
        return {}

    @register_tool("b", "", _GetTimeArgs)
    def _b():
        return {}

    snapshot = get_tools()
    snapshot.clear()                    # mutate the snapshot
    assert has_tool("a") and has_tool("b")   # registry intact


# ── ToolDef renders three ways ───────────────────────────────────────


def test_tool_def_renders_anthropic_schema():
    @register_tool("get_time", "Get the time.", _GetTimeArgs)
    def _impl(timezone: str = "UTC"):
        return {}

    schema = get_tool("get_time").to_anthropic_schema()
    assert schema["name"] == "get_time"
    assert schema["description"] == "Get the time."
    assert "input_schema" in schema
    assert schema["input_schema"]["type"] == "object"


def test_tool_def_renders_openai_schema():
    @register_tool("get_time", "Get the time.", _GetTimeArgs)
    def _impl(timezone: str = "UTC"):
        return {}

    schema = get_tool("get_time").to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_time"
    assert "parameters" in schema["function"]


def test_tool_def_renders_hermes_xml_block_as_valid_json():
    import json

    @register_tool("get_time", "Get the time.", _GetTimeArgs)
    def _impl(timezone: str = "UTC"):
        return {}

    block = get_tool("get_time").to_hermes_xml_block()
    parsed = json.loads(block)
    assert parsed["type"] == "function"
    assert parsed["function"]["name"] == "get_time"


# ── ToolDef.dispatch validates args via Pydantic ────────────────────


def test_dispatch_validates_args_then_calls_handler():
    captured = {}

    @register_tool("get_time", "Get the time.", _GetTimeArgs)
    def _impl(timezone: str = "UTC") -> dict:
        captured["seen"] = timezone
        return {"time": "12:00"}

    result = get_tool("get_time").dispatch({"timezone": "Asia/Tokyo"})
    assert captured["seen"] == "Asia/Tokyo"
    assert result == {"time": "12:00"}


def test_dispatch_raises_validation_error_on_bad_args():
    """Bad args propagate as ``ValidationError`` — the agent loop
    catches it and converts to a tool result so the model self-corrects
    rather than crashing the turn."""
    from pydantic import ValidationError

    @register_tool("move_joint", "Move a joint.", _MoveJointArgs)
    def _impl(joint_id: int, target_angle_rad: float):
        return {}

    with pytest.raises(ValidationError):
        get_tool("move_joint").dispatch({"joint_id": 99, "target_angle_rad": 0.0})


# ── ProviderAdapter ABC contract ─────────────────────────────────────


def test_adapter_abc_blocks_instantiation_without_overrides():
    """Subclasses that skip required methods must fail to instantiate —
    the spec's contract is enforced by Python, not by docs."""
    class _Incomplete(ProviderAdapter):
        def format_messages(self, *a, **k):
            return None
        # missing call, parse_response, supports

    with pytest.raises(TypeError):
        _Incomplete()


def test_noop_adapter_implements_full_contract():
    a = _NoOpAdapter()
    assert a.name == "noop"
    assert a.format_messages([], [], "") == {"messages": [], "tools": [], "system": ""}
    raw = a.call({}, threading.Event())
    parsed = a.parse_response(raw)
    assert parsed["role"] == "assistant"
    assert a.supports("anything") is False
    health = a.health_check()
    assert health["ok"] is True
    assert "JaegerAgent" not in a.describe()
    assert "noop" in a.describe()


# ── JaegerAgent skeleton ─────────────────────────────────────────────


def test_jaeger_agent_constructs_with_minimum_args():
    agent = JaegerAgent(adapter=_NoOpAdapter())
    assert agent.primary_adapter.name == "noop"
    assert agent.messages == []
    assert agent.max_iterations == 50
    assert agent.callbacks is not None
    assert agent.interrupted is False


def test_jaeger_agent_run_turn_appends_user_then_assistant():
    """Phase-2: ``run_turn`` drives a real loop. The no-op adapter
    returns a plain assistant message with no tool calls — exactly the
    single-iteration happy path."""
    agent = JaegerAgent(adapter=_NoOpAdapter())
    result = agent.run_turn("hello")
    assert len(agent.messages) == 2
    assert agent.messages[0] == {"role": "user", "content": "hello"}
    assert agent.messages[1]["role"] == "assistant"
    assert agent.messages[1]["content"] == "(noop)"
    assert result == "(noop)"
    assert agent.last_iteration_count == 1
    assert agent.last_halt_reason is None


def test_jaeger_agent_interrupt_sets_and_resets_cleanly():
    fired = []
    agent = JaegerAgent(
        adapter=_NoOpAdapter(),
        callbacks=AgentCallbacks(interrupt=lambda: fired.append(1)),
    )
    assert agent.interrupted is False
    agent.interrupt()
    assert agent.interrupted is True
    assert fired == [1]                # the interrupt callback fired
    agent.reset_interrupt()
    assert agent.interrupted is False


def test_jaeger_agent_uses_explicit_tools_when_provided():
    @register_tool("a", "", _GetTimeArgs)
    def _a():
        return {}

    @register_tool("b", "", _GetTimeArgs)
    def _b():
        return {}

    only_a = JaegerAgent(adapter=_NoOpAdapter(), tools=[get_tool("a")])
    assert only_a.tool_names() == ["a"]


def test_jaeger_agent_uses_registry_when_tools_unspecified():
    @register_tool("registry_only", "", _GetTimeArgs)
    def _impl():
        return {}

    agent = JaegerAgent(adapter=_NoOpAdapter())
    assert "registry_only" in agent.tool_names()


# ── Interruptible call primitive ─────────────────────────────────────


def test_interruptible_call_returns_result_on_normal_completion():
    ev = threading.Event()
    out = interruptible_call(lambda: 42, ev)
    assert out == 42


def test_interruptible_call_reraises_inner_exceptions():
    ev = threading.Event()

    def _explode():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        interruptible_call(_explode, ev)


def test_interruptible_call_raises_agent_interrupted_when_event_fires():
    ev = threading.Event()
    started = threading.Event()
    can_finish = threading.Event()

    def _slow() -> str:
        started.set()
        can_finish.wait(timeout=2.0)         # block until we let it go
        return "done"

    def _interrupter():
        started.wait(timeout=1.0)
        ev.set()                              # fire interrupt mid-call

    threading.Thread(target=_interrupter, daemon=True).start()
    with pytest.raises(AgentInterrupted):
        interruptible_call(_slow, ev, poll_interval=0.02)
    # Let the abandoned worker exit so pytest's worker leak detector
    # doesn't flag us.
    can_finish.set()


# ── Callback safe-invocation ─────────────────────────────────────────


def test_callbacks_swallow_handler_exceptions():
    """A buggy observer must never break the agent turn."""
    cb = AgentCallbacks(tool_progress=lambda *_: 1 / 0)
    # Should not raise.
    cb.on_tool_progress("get_time", "start", {})


def test_callbacks_noop_when_handlers_absent():
    cb = AgentCallbacks()
    # All five hooks no-op cleanly.
    cb.on_tool_progress("x", "start", {})
    cb.on_thinking("…")
    cb.on_stream_delta("token")
    cb.on_step(0, {"role": "assistant", "content": ""})
    cb.on_interrupt()
