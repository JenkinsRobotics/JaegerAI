"""Shared CommitmentStore contract — durable SI intentions."""

from __future__ import annotations

import pytest

from jaeger_agent.cognition.commitments import (
    CommitmentError,
    InMemoryCommitmentStore,
)


@pytest.fixture
def store():
    return InMemoryCommitmentStore()


def test_create_starts_in_created(store):
    item = store.create("ship the refactor")
    assert item.state == "created"
    assert store.get(item.id) is item


def test_legal_transition_is_recorded(store):
    item = store.create("ship")
    store.transition(item.id, "active")
    store.transition(item.id, "completed")
    assert store.get(item.id).state == "completed"


def test_illegal_transition_does_not_mutate(store):
    item = store.create("ship")
    with pytest.raises(CommitmentError, match="cannot move"):
        store.transition(item.id, "completed")
    assert store.get(item.id).state == "created"


def test_terminal_completed_cannot_move(store):
    item = store.create("ship")
    store.transition(item.id, "active")
    store.transition(item.id, "completed")
    with pytest.raises(CommitmentError):
        store.transition(item.id, "active")


def test_failed_can_resume(store):
    item = store.create("ship")
    store.transition(item.id, "active")
    store.transition(item.id, "failed")
    store.transition(item.id, "active")
    assert store.get(item.id).state == "active"


def test_list_filters_by_state(store):
    a = store.create("a")
    b = store.create("b")
    store.transition(a.id, "active")
    assert {row.id for row in store.list(state="created")} == {b.id}
    assert {row.id for row in store.list(state="active")} == {a.id}
