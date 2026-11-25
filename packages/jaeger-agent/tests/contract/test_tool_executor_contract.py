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


@pytest.mark.parametrize("name", ["terminal", "exec_command"])
def test_shell_test_can_run_again_after_an_edit(tmp_path, name):
    import subprocess
    import sys

    from jaeger_agent import LedgerToolExecutor
    from jaeger_agent.cognition.effects import InMemoryEffectLedger
    from jaeger_events.live import tool_call

    class Args(BaseModel):
        cmd: str

    checked_file = tmp_path / "value.txt"
    checked_file.write_text("before")
    invocations = []

    def run(cmd):
        invocations.append(cmd)
        return subprocess.run([sys.executable, "-c", cmd], cwd=tmp_path).returncode

    tool = ToolDef(name=name, description="Shell", fn=run, args_model=Args, side_effect="external")
    command = {"cmd": "from pathlib import Path; assert Path('value.txt').read_text() == 'after'"}
    ledger = InMemoryEffectLedger()
    executor = LedgerToolExecutor(ledger, run_id="run-1")
    with tool_call("first-test"):
        assert executor.execute(tool, command) != 0
    checked_file.write_text("after")
    with tool_call("second-test"):
        assert executor.execute(tool, command) == 0
    checked_file.write_text("before")
    with tool_call("second-test"):
        assert LedgerToolExecutor(ledger, run_id="run-1").execute(tool, command) == 0
    assert len(invocations) == 2


def test_shell_preserves_existing_argument_key_on_upgrade():
    from jaeger_agent import LedgerToolExecutor
    from jaeger_agent.cognition.effects import InMemoryEffectLedger
    from jaeger_events.live import tool_call

    class Args(BaseModel):
        cmd: str

    calls = []
    tool = ToolDef(name="terminal", description="Shell", fn=lambda cmd: calls.append(cmd) or "old",
                   args_model=Args, side_effect="external")
    executor = LedgerToolExecutor(InMemoryEffectLedger(), run_id="existing-run")
    assert executor.execute(tool, {"cmd": "echo hi"}) == "old"
    with tool_call("restored-call"):
        assert executor.execute(tool, {"cmd": "echo hi"}) == "old"
    assert calls == ["echo hi"]


def test_agent_executes_identical_test_command_after_edit():
    from jaeger_agent import LedgerToolExecutor
    from jaeger_agent.cognition.effects import InMemoryEffectLedger

    class ShellArgs(BaseModel):
        cmd: str

    results = []
    workspace = {"fixed": False}

    def run_test(cmd):
        results.append(workspace["fixed"])
        return {"ok": workspace["fixed"]}

    def edit(value):
        workspace["fixed"] = True
        return {"ok": True}

    shell = ToolDef(name="exec_command", description="Run tests", fn=run_test,
                    args_model=ShellArgs, side_effect="external")
    before = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "provider-reused-id", "name": "exec_command", "arguments": {"cmd": "run tests"}},
    ]}
    adapter = _ScriptedAdapter()
    adapter.script = [before, {"role": "assistant", "content": None, "tool_calls": [
        {"id": "edit", "name": "double", "arguments": {"value": 4}},
    ]}, before, {"role": "assistant", "content": "verified"}]
    agent = JaegerAgent(adapter=adapter, tools=[shell, _tool(edit)],
                       tool_executor=LedgerToolExecutor(InMemoryEffectLedger()))
    agent.bind_run("run-1")

    assert agent.run_turn("Fix the problem and rerun the tests") == "verified"
    assert results == [False, True]


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
    # A run must exist DURING the turn — the ledger needs one to claim keys —
    # and an ephemeral run (one the agent opened for itself, because no host
    # bound one) must be released at the end, or its id leaks into the next
    # turn. This asserted ``agent.run_id`` after the turn, which contradicts
    # that release and had been failing since it was introduced.
    seen: list[object] = []
    original_bind = agent.bind_run
    agent.bind_run = lambda run_id: (seen.append(run_id), original_bind(run_id))[1]

    assert agent.run_turn("hello") == "ok"

    assert any(r for r in seen), "no run was opened for the turn"
    assert agent.run_id is None, "an ephemeral run must be released at turn end"




def test_child_allowlist_survives_catalog_injection_and_context_exit():
    from jaeger_agent.tool_executor import tool_allowlist, active_tool_allowlist
    executor = _RecordingExecutor()
    with tool_allowlist([]):
        agent = JaegerAgent(adapter=_ScriptedAdapter(), tools=[_tool()], tool_executor=executor)
        with tool_allowlist(['double']):
            assert active_tool_allowlist() == frozenset()
    assert active_tool_allowlist() is None
    # Simulate overflow/catalog refresh accidentally advertising a denied tool.
    agent._dispatch_by_name['double'] = _tool()
    agent.run_turn('attempt a denied tool')
    assert executor.calls == []
    assert agent.allowed_tools == frozenset()
    assert any('permission_denied' in str(m.get('content')) for m in agent.messages)


def test_child_allowlist_allows_granted_tool():
    from jaeger_agent.tool_executor import tool_allowlist
    executor = _RecordingExecutor()
    with tool_allowlist(['double']):
        agent = JaegerAgent(adapter=_ScriptedAdapter(), tools=[_tool()], tool_executor=executor)
    agent.run_turn('double four')
    assert executor.calls == [('double', {'value': 4})]
