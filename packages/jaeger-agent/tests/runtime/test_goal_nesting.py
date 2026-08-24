"""Parent goals cannot complete while their children are open.

"The subtasks are basically done" is precisely the judgement a language
model should not be trusted with, so it is not a judgement at all here —
it is a query against the children table.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.commitments import (
    CommitmentError,
    InMemoryCommitmentStore,
)
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryCommitmentStore()
        return
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteCommitmentStore()
    finally:
        sqlite_store.close()


def test_children_are_listed_under_their_parent(store):
    parent = store.create("ship the refactor")
    child = store.create("write the migration", parent_id=parent.id)
    store.create("unrelated errand")

    assert [c.id for c in store.children(parent.id)] == [child.id]
    assert store.get(child.id).parent_id == parent.id


def test_parent_cannot_complete_with_an_open_child(store):
    parent = store.create("ship the refactor")
    child = store.create("write the migration", parent_id=parent.id)
    store.transition(parent.id, "active")

    with pytest.raises(CommitmentError, match="open children"):
        store.transition(parent.id, "completed")

    assert store.get(parent.id).state == "active"
    assert store.get(child.id).state == "created"


def test_parent_completes_once_children_are_terminal(store):
    parent = store.create("ship the refactor")
    child = store.create("write the migration", parent_id=parent.id)
    store.transition(parent.id, "active")
    store.transition(child.id, "active")
    store.transition(child.id, "completed")

    store.transition(parent.id, "completed")

    assert store.get(parent.id).state == "completed"


def test_a_cancelled_child_does_not_block_the_parent(store):
    parent = store.create("ship the refactor")
    child = store.create("optional polish", parent_id=parent.id)
    store.transition(parent.id, "active")
    store.transition(child.id, "cancelled")

    store.transition(parent.id, "completed")

    assert store.get(parent.id).state == "completed"


def test_a_failed_child_still_blocks_the_parent(store):
    """``failed`` is resumable, so the work is not finished."""
    parent = store.create("ship the refactor")
    child = store.create("write the migration", parent_id=parent.id)
    store.transition(parent.id, "active")
    store.transition(child.id, "active")
    store.transition(child.id, "failed")

    with pytest.raises(CommitmentError, match="open children"):
        store.transition(parent.id, "completed")


def test_a_parent_may_be_cancelled_with_open_children(store):
    """Cancelling is abandoning the subtree, not claiming it finished."""
    parent = store.create("ship the refactor")
    store.create("write the migration", parent_id=parent.id)

    store.transition(parent.id, "cancelled")

    assert store.get(parent.id).state == "cancelled"


def test_unknown_parent_is_rejected(store):
    with pytest.raises(CommitmentError, match="no parent commitment"):
        store.create("orphan", parent_id="does-not-exist")


def test_nesting_survives_a_rebind(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        store = SqliteCommitmentStore()
        parent = store.create("ship the refactor")
        child = store.create("write the migration", parent_id=parent.id)
        parent_id, child_id = parent.id, child.id
    finally:
        sqlite_store.close()

    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        store = SqliteCommitmentStore()
        assert [c.id for c in store.children(parent_id)] == [child_id]
        store.transition(parent_id, "active")
        with pytest.raises(CommitmentError, match="open children"):
            store.transition(parent_id, "completed")
    finally:
        sqlite_store.close()
