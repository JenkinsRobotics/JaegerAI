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

