"""Shared contract and consumer swap test for tool execution."""

from __future__ import annotations

from typing import Any, Mapping

import pytest
from pydantic import BaseModel, Field, ValidationError

from jaeger_agent import (
    DirectToolExecutor,
    JaegerAgent,
    Message,
    ProviderAdapter,
    ToolDef,
    ToolExecutor,
)


class _Args(BaseModel):
    value: int = Field(ge=1)


def _tool(fn=lambda value: value * 2) -> ToolDef:
    return ToolDef(name="double", description="Double a value", args_model=_Args, fn=fn)


def test_direct_executor_satisfies_contract_and_preserves_validation():
    executor = DirectToolExecutor()
    assert isinstance(executor, ToolExecutor)
    assert executor.execute(_tool(), {"value": 3}) == 6
    with pytest.raises(ValidationError):
        executor.execute(_tool(), {"value": 0})


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, tool: ToolDef, arguments: Mapping[str, Any]) -> Any:
        self.calls.append((tool.name, dict(arguments)))
        return {"executed_by": "recording", "value": arguments["value"]}


class _ScriptedAdapter(ProviderAdapter):
    name = "scripted"

    def __init__(self) -> None:
        self.script: list[Message] = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-1", "name": "double", "arguments": {"value": 4}},
                ],
            },
            {"role": "assistant", "content": "done"},
        ]

    def format_messages(self, messages, tools, system):
        return messages

    def call(self, formatted, interrupt_event, **kwargs):
        return self.script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature: str) -> bool:
        return False


def test_agent_consumer_swaps_executor_without_tool_or_loop_changes():
    def must_not_run(value: int) -> int:
        raise AssertionError("ToolDef.dispatch bypassed the injected executor")

    executor = _RecordingExecutor()
    agent = JaegerAgent(
        adapter=_ScriptedAdapter(),
        tools=[_tool(must_not_run)],
        tool_executor=executor,
    )

    assert agent.run_turn("double four") == "done"
    assert executor.calls == [("double", {"value": 4})]
    tool_message = next(message for message in agent.messages if message["role"] == "tool")
    assert '"executed_by": "recording"' in tool_message["content"]


def test_ledger_executor_runs_authoritative_tools_at_most_once():
    from jaeger_agent.cognition.effects import InMemoryEffectLedger
    from jaeger_agent import LedgerToolExecutor

    calls: list[int] = []

    class _ExternalArgs(BaseModel):
        to: str

    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_ExternalArgs,
        fn=lambda to: calls.append(to) or {"sent": True, "to": to},
        side_effect="external",
    )
    ledger = InMemoryEffectLedger()
    executor = LedgerToolExecutor(ledger, run_id="run-1")
    first = executor.execute(tool, {"to": "a@b.c"})
    resumed = LedgerToolExecutor(ledger, run_id="run-1")
    second = resumed.execute(tool, {"to": "a@b.c"})
    assert first == second == {"sent": True, "to": "a@b.c"}
    assert calls == ["a@b.c"]


def test_new_run_may_repeat_the_same_external_call():
    from jaeger_agent.cognition.effects import InMemoryEffectLedger
    from jaeger_agent import LedgerToolExecutor

    calls: list[str] = []

    class _ExternalArgs(BaseModel):
        to: str

    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_ExternalArgs,
        fn=lambda to: calls.append(to) or {"sent": True, "to": to},
        side_effect="external",
    )
    ledger = InMemoryEffectLedger()
    LedgerToolExecutor(ledger, run_id="run-1").execute(tool, {"to": "a@b.c"})
    LedgerToolExecutor(ledger, run_id="run-2").execute(tool, {"to": "a@b.c"})
    assert calls == ["a@b.c", "a@b.c"]


def test_validation_failure_does_not_claim_the_ledger():
    from jaeger_agent.cognition.effects import InMemoryEffectLedger
    from jaeger_agent import LedgerToolExecutor

    class _ExternalArgs(BaseModel):
        to: str = Field(min_length=3)

    tool = ToolDef(
        name="send_email",
        description="Send",
        args_model=_ExternalArgs,
        fn=lambda to: {"sent": True},
        side_effect="external",
    )
    ledger = InMemoryEffectLedger()
    executor = LedgerToolExecutor(ledger, run_id="run-1")
    with pytest.raises(ValidationError):
        executor.execute(tool, {"to": "ab"})
    assert ledger.list() == []


def test_agent_defaults_to_ledger_executor():
    """At-most-once is on by default, with hooks composed OUTSIDE it.

    The ordering is the load-bearing part, not just the membership: a
    ``pre_tool_call`` veto has to stop the call before ``EffectLedger.once``
    claims its key. Hooks inside the ledger would let a block burn the key,
    so the retry after the operator fixes their hook would come back as a
    duplicate instead of running.
    """
    adapter = _ScriptedAdapter()
    adapter.script = [{"role": "assistant", "content": "ok"}]
    agent = JaegerAgent(adapter=adapter, tools=[])
    from jaeger_agent.tool_executor import (
        CheckpointingToolExecutor, HookedToolExecutor, LedgerToolExecutor,
    )
    # hooks → checkpoints → ledger. Walk the chain rather than asserting one
    # type, so a future layer inserted in the wrong place fails here.
    outer = agent._tool_executor
    assert isinstance(outer, HookedToolExecutor)
    assert isinstance(outer._inner, CheckpointingToolExecutor)
    assert isinstance(outer._inner._inner, LedgerToolExecutor)
    assert agent.run_turn("hello") == "ok"
    assert agent.run_id


