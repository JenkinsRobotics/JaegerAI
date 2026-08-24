"""Shared contract for ScheduleStore adapters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_agent.memory.in_memory_schedules import InMemoryScheduleStore
from jaeger_agent.memory.schedule_port import ScheduleStore
from jaeger_agent.memory.sqlite_schedules import SqliteScheduleStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path) -> ScheduleStore:
    if request.param == "memory":
        yield InMemoryScheduleStore()
        return
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        yield SqliteScheduleStore()
    finally:
        sqlite_store.close()


def test_store_satisfies_protocol(store):
    assert isinstance(store, ScheduleStore)


def test_add_list_cancel(store):
    row = store.add("0 7 * * *", "morning briefing", name="brief")
    assert row["name"] == "brief"
    assert row["prompt"] == "morning briefing"
    listed = store.list()
    assert [r["name"] for r in listed] == ["brief"]
    assert store.cancel("brief") is True
    assert store.list() == []
    assert store.cancel("brief") is False


def test_add_requires_prompt_and_when(store):
    with pytest.raises(ValueError):
        store.add("", "", name="empty")
