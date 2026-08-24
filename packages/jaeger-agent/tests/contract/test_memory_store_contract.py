"""Shared MemoryStore contract — every adapter must pass these tests.

Swap the ``store`` fixture to prove a new backend is a drop-in.
"""

from __future__ import annotations

import pytest

from jaeger_agent.memory.in_memory import InMemoryMemoryStore
from jaeger_agent.memory.port import MemoryStore


@pytest.fixture(params=["memory"])
def store(request) -> MemoryStore:
    if request.param == "memory":
        return InMemoryMemoryStore()
    raise AssertionError(request.param)


def test_store_satisfies_protocol(store):
    assert isinstance(store, MemoryStore)


def test_remember_then_recall(store):
    store.remember("colour", "blue")
    assert store.recall("colour") == "blue"


def test_forget_removes_the_fact(store):
    store.remember("colour", "blue")
    assert store.forget("colour") is True
    assert store.recall("colour") is None
    assert store.forget("colour") is False


def test_subjects_do_not_clobber_each_other(store):
    store.remember("colour", "blue", subject="user")
    store.remember("colour", "green", subject="ares")
    assert store.recall("colour", subject="user") == "blue"
    assert store.recall("colour", subject="ares") == "green"
    assert store.list_facts(subject="user") == {"colour": "blue"}


def test_episodic_round_trip_is_session_scoped(store):
    store.append_episodic({"user": "hi", "answer": "hello", "session_key": "a"})
    store.append_episodic({"user": "bye", "answer": "later", "session_key": "b"})
    a = store.load_recent_turns(5, session_key="a")
    assert len(a) == 1
    assert a[0]["user"] == "hi"
    assert a[0]["answer"] == "hello"
