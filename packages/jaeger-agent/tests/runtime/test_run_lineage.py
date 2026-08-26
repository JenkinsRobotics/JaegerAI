from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.commitments import InMemoryCommitmentStore
from jaeger_agent.cognition.runs import InMemoryRunStore, RunError
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture(params=["memory", "sqlite"])
def stores(request, tmp_path):
    if request.param == "memory":
        yield InMemoryCommitmentStore(), InMemoryRunStore()
        return
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteCommitmentStore(), SqliteRunStore()
    finally:
        sqlite_store.close()


def test_parent_root_and_relation_form_one_durable_tree(stores):
    commitments, runs = stores
    commitment = commitments.create("ship feature")
    root = runs.create(commitment.id)
    delegated = runs.create(commitment.id, parent_run_id=root.id, relation="delegated")
    background = runs.create(commitment.id, parent_run_id=delegated.id, relation="background")

    assert delegated.root_run_id == root.id
    assert background.root_run_id == root.id
    assert [run.id for run in runs.children(root.id)] == [delegated.id]
    assert [run.id for run in runs.lineage(background.id)] == [root.id, delegated.id, background.id]
    assert [run.relation for run in runs.lineage(root.id)] == ["root", "delegated", "background"]


def test_missing_parent_fails_closed(stores):
    commitments, runs = stores
    commitment = commitments.create("ship feature")
    with pytest.raises(RunError, match="no parent run"):
        runs.create(commitment.id, parent_run_id="missing", relation="delegated")
