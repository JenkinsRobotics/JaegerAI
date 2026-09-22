"""One request, one run; a dead owner's run is recoverable, not "active".

Live state found by the 2026-09-21 audit: every Gateway restart relabelled
~450 orphaned runs ``active`` under the new pid with nothing executing them,
and ``TurnExecutive.ensure_run`` handed the oldest one to the next unrelated
request. Effect keys are scoped by run id, so a later request's identical write
could be skipped as already done.

Production-path integration: real SQLite run store, effect ledger, commitment
store and RecoveryManager; only the model loop is scripted.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.recovery import RecoveryManager


class _Agent:
    def __init__(self) -> None:
        self.run_id = None
        self.last_halt_reason = None
        self.last_iteration_count = 1
        self.primary_adapter = SimpleNamespace(name="test")

    def bind_run(self, run_id):
        self.run_id = run_id

    def run_turn(self, text):
        return "ok"


@pytest.fixture
def stores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from jaeger_agent.cognition.executive import TURN_LOOP_KIND
    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
    from jaeger_agent.memory import sqlite_store

    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    commits = SqliteCommitmentStore()
    commitment = commits.create(TURN_LOOP_KIND, kind=TURN_LOOP_KIND)
    commits.transition(commitment.id, "active")
    return SimpleNamespace(
        commits=commits, runs=SqliteRunStore(), ledger=SqliteEffectLedger(),
        commitment_id=commitment.id,
    )


def test_a_new_request_does_not_adopt_another_requests_active_run(stores):
    from jaeger_agent.cognition.executive import TurnExecutive

    foreign = stores.runs.transition(stores.runs.create(stores.commitment_id, owner_pid=1).id, "active")

    run = TurnExecutive(_Agent(), stores.runs, stores.commits, provider="test").ensure_run()

    assert run.id != foreign.id
    assert stores.runs.get(foreign.id).state == "active"


def test_orphaned_run_is_recoverable_and_a_bound_resume_skips_done_work(stores):
    from jaeger_agent.cognition.executive import TurnExecutive

    run = stores.runs.transition(stores.runs.create(stores.commitment_id, owner_pid=999999).id, "active")
    key = f'{run.id}:write_file:{{"path":"a.txt"}}'
    stores.ledger.once(key, "write_file", lambda: {"written": True}, run_id=run.id)
    stores.runs.recover(is_alive=lambda pid: False)

    report = RecoveryManager().scan_resumable_runs()

    assert run.id in report.recoverable
    assert run.id not in report.resumed
    assert stores.runs.get(run.id).state == "recoverable"

    agent = _Agent()
    agent.bind_run(run.id)
    resumed = TurnExecutive(agent, stores.runs, stores.commits, provider="test").ensure_run()

    assert resumed.id == run.id
    assert resumed.state == "active"
    _, executed = stores.ledger.once(key, "write_file", lambda: {"written": "AGAIN"}, run_id=run.id)
    assert executed is False
