"""Concurrent unbound turns share an intention, never an execution run."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.commitments import CommitmentError, InMemoryCommitmentStore
from jaeger_agent.cognition.executive import TURN_LOOP_KIND, TurnExecutive
from jaeger_agent.cognition.runs import InMemoryRunStore
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture(params=['memory', 'sqlite'])
def stores(request, tmp_path):
    if request.param == 'sqlite':
        sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
        try:
            yield SqliteCommitmentStore(), SqliteRunStore()
        finally:
            sqlite_store.close()
    else:
        yield InMemoryCommitmentStore(), InMemoryRunStore()


class Loop:
    run_id = None
    primary_adapter = SimpleNamespace(name='scripted')

    def bind_run(self, run_id):
        self.run_id = run_id


def test_competing_ensure_run_activates_one_commitment(stores, monkeypatch):
    commitments, runs = stores
    seeded = commitments.create(TURN_LOOP_KIND, kind=TURN_LOOP_KIND)
    # Reproduce the observed interleaving: both readers see created before
    # either activates. Snapshots model SQLite rows for both adapters.
    read_barrier = Barrier(2)
    original_list = commitments.list
    def competing_list(**kwargs):
        rows = [replace(row) for row in original_list(**kwargs)]
        read_barrier.wait(timeout=5)
        return rows
    monkeypatch.setattr(commitments, 'list', competing_list)
    transition_lock = Lock()
    original_transition = commitments.transition
    def serialized_transition(*args, **kwargs):
        with transition_lock:
            return original_transition(*args, **kwargs)
    monkeypatch.setattr(commitments, 'transition', serialized_transition)
    start = Barrier(2)
    def execute(_):
        start.wait(timeout=5)
        return TurnExecutive(Loop(), runs, commitments).ensure_run()
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(execute, range(2)))
    assert len({run.id for run in result}) == 2
    assert {run.commitment_id for run in result} == {seeded.id}
    assert all(run.state == 'active' for run in result)
    assert commitments.get(seeded.id).state == 'active'
    # Atomic acquisition must not relax strict public lifecycle transitions.
    with pytest.raises(CommitmentError, match='active to active'):
        commitments.transition(seeded.id, 'active')


def test_competing_first_turns_create_one_intention(stores):
    commitments, runs = stores
    start = Barrier(8)
    def execute(_):
        start.wait(timeout=5)
        return TurnExecutive(Loop(), runs, commitments).ensure_run()
    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(execute, range(8)))
    assert len({run.id for run in result}) == 8
    assert len({run.commitment_id for run in result}) == 1
    assert len(commitments.list()) == 1


def test_only_open_matching_kind_is_reused(stores):
    commitments, runs = stores
    other = commitments.create('project', kind='project')
    old = commitments.create(TURN_LOOP_KIND, kind=TURN_LOOP_KIND)
    commitments.transition(old.id, 'active')
    commitments.transition(old.id, 'completed')
    run = TurnExecutive(Loop(), runs, commitments).ensure_run()
    assert run.commitment_id not in {other.id, old.id}
    next_run = TurnExecutive(Loop(), runs, commitments).ensure_run()
    assert next_run.commitment_id == run.commitment_id
    assert next_run.id != run.id
