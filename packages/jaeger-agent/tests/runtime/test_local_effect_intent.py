"""T03: every non-read tool call leaves durable intent/outcome evidence.

External effects keep args-keyed crash-replay protection. Local writes,
hardware and unclassified calls (fail closed: unclassified is a mutation)
get a per-invocation record: never deduplicated, resolved on any observed
outcome, left pending only when the process dies inside the call — which is
what lets a run's outcome be reported unknown instead of guessed.
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

from jaeger_agent.cognition.effects import InMemoryEffectLedger
from jaeger_agent.tool_executor import DirectToolExecutor, LedgerToolExecutor
from jaeger_os.core.tools.tool_schema import ToolDef


class _Args(BaseModel):
    value: str = "x"


class _ProcessDeath(BaseException):
    pass


def _tool(side_effect, fn):
    return ToolDef(name=f"t_{side_effect or 'unclassified'}", description="d",
                   args_model=_Args, fn=fn, side_effect=side_effect)


def _executor(ledger):
    return LedgerToolExecutor(ledger, DirectToolExecutor(), run_id="run-1")


@pytest.mark.parametrize("side_effect", ["write", "hardware", ""])
def test_repeated_identical_local_calls_both_run_and_both_are_recorded(side_effect):
    ledger, calls = InMemoryEffectLedger(), []
    tool = _tool(side_effect, lambda value="x": calls.append(value) or {"n": len(calls)})

    first = _executor(ledger).execute(tool, {"value": "same"})
    second = _executor(ledger).execute(tool, {"value": "same"})

    assert calls == ["same", "same"], "a deliberate repeat is new intent"
    assert (first, second) == ({"n": 1}, {"n": 2})
    done = ledger.list(status="done")
    assert len(done) == 2 and all(e.run_id == "run-1" for e in done)
    assert ledger.list(status="pending") == []


def test_ordinary_tool_error_is_an_observed_outcome_not_unknown():
    ledger = InMemoryEffectLedger()

    def boom(value="x"):
        raise FileNotFoundError("nope")

    with pytest.raises(FileNotFoundError):
        _executor(ledger).execute(_tool("write", boom), {})
    assert ledger.list(status="pending") == []
    assert ledger.list(status="done")[0].result == {"ok": False, "error": "FileNotFoundError"}


def test_process_death_inside_a_local_write_leaves_it_pending():
    ledger = InMemoryEffectLedger()

    def dies(value="x"):
        raise _ProcessDeath()

    with pytest.raises(_ProcessDeath):
        _executor(ledger).execute(_tool("write", dies), {})
    pending = ledger.list(status="pending")
    assert len(pending) == 1 and pending[0].run_id == "run-1"


def test_reads_are_not_recorded():
    ledger = InMemoryEffectLedger()
    _executor(ledger).execute(_tool("read", lambda value="x": value), {})
    assert ledger.list() == []


def test_external_effects_keep_args_keyed_replay_protection():
    ledger, calls = InMemoryEffectLedger(), []
    tool = _tool("external", lambda value="x": calls.append(value) or "sent")
    _executor(ledger).execute(tool, {"value": "a"})
    _executor(ledger).execute(tool, {"value": "a"})
    assert calls == ["a"], "a crash replay of the same run must not re-send"
