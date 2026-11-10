"""Execution invariants reproduced by the BFCL baseline fault probes."""
import json
import threading

from pydantic import BaseModel

from jaeger_agent import JaegerAgent, ProviderAdapter
from jaeger_agent.loop.callbacks import AgentCallbacks
from jaeger_agent.loop.turn_budget import TurnBudgetLimits
from jaeger_agent.loop.tool_dispatch_safety import paths_overlap
from jaeger_os.core.tools.tool_schema import ToolDef


class Number(BaseModel):
    value: int


class Scripted(ProviderAdapter):
    name = "invariant-fixture"

    def __init__(self, steps):
        self.steps = iter(steps)

    def format_messages(self, messages, tools, system):
        return messages

    def call(self, formatted, interrupt_event, **kwargs):
        return next(self.steps, {"role": "assistant", "content": "Finished."})

    def parse_response(self, raw):
        return raw

    def supports(self, feature):
        return False


def calls(values, ids=None):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": ids[i] if ids else str(i), "name": "read_n", "arguments": {"value": n}}
        for i, n in enumerate(values)
    ]}


def test_cancel_does_not_start_queued_work_and_closes_all_results():
    barrier = threading.Barrier(4)
    cancelled = threading.Event()
    started = []

    def read_n(value):
        started.append((value, cancelled.is_set()))
        if value < 4:
            barrier.wait(3)
            if value == 0:
                agent.interrupt()
                cancelled.set()
            assert cancelled.wait(3)
        return {"value": value}

    agent = JaegerAgent(Scripted([calls(range(5))]), tools=[
        ToolDef("read_n", "fixture", Number, read_n, side_effect="read")])
    agent.run_turn("Read five independent values.")
    assert sorted(value for value, _ in started) == [0, 1, 2, 3]
    results = [m for m in agent.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in results] == [str(i) for i in range(5)]
    assert json.loads(results[-1]["content"])["error_type"] == "interrupted"


def test_duplicate_and_missing_ids_are_unique_across_turns():
    agent = JaegerAgent(Scripted([
        calls([1, 2, 3], ["duplicate", "duplicate", ""]),
        {"role": "assistant", "content": "Finished."},
        calls([4], ["duplicate"]),
    ]), tools=[ToolDef("read_n", "fixture", Number, lambda value: value, side_effect="read")])
    agent.run_turn("Read three values.")
    agent.run_turn("Read another value.")
    admitted = [c for m in agent.messages for c in m.get("tool_calls", [])]
    ids = [c["id"] for c in admitted]
    assert len(ids) == len(set(ids)) == 4 and all(ids)
    assert admitted[1]["provider_id"] == admitted[3]["provider_id"] == "duplicate"
    assert [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"] == ids


def test_file_aliases_and_unresolved_paths_serialize(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert paths_overlap(str(real / "new"), str(alias / "new"))
    target = real / "file"
    target.write_text("fixture")
    hardlink = tmp_path / "hardlink"
    hardlink.hardlink_to(target)
    assert paths_overlap(str(target), str(hardlink))
    assert paths_overlap("relative", str(target))
    assert paths_overlap(str(real), str(alias / "child"))
    assert not paths_overlap(str(real / "one"), str(real / "two"))


def test_finalization_does_not_replace_execution_tool_receipt():
    receipts = []
    agent = JaegerAgent(Scripted([calls([1])]), tools=[
        ToolDef("read_n", "fixture", Number, lambda value: value, side_effect="read")],
        callbacks=AgentCallbacks(tool_selection=receipts.append),
        turn_budget_limits=TurnBudgetLimits(max_iterations=1, max_tool_calls=10))
    agent.run_turn("Read a value and summarize.")
    assert receipts and all(r["selected_count"] == 1 for r in receipts)


def test_direct_executor_checks_request_cancellation():
    from jaeger_agent.core.cancellation import turn_cancellation
    from jaeger_agent.tool_executor import DirectToolExecutor
    executed = []
    event = threading.Event()
    event.set()
    with turn_cancellation(event):
        result = DirectToolExecutor().execute(
            ToolDef("read_n", "fixture", Number, lambda value: executed.append(value)), {"value": 1})
    assert not executed
    assert result["error_type"] == "interrupted"
