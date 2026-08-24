"""SQLite commitment adapter survives reopen — the durable SI property."""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.memory import sqlite_store


def test_commitment_survives_rebind(tmp_path):
    layout = SimpleNamespace(memory_dir=tmp_path)
    sqlite_store.bind(layout)
    try:
        store = SqliteCommitmentStore()
        item = store.create("finish the refactor")
        store.transition(item.id, "active")
        cid = item.id
    finally:
        sqlite_store.close()

    sqlite_store.bind(layout)
    try:
        restored = SqliteCommitmentStore().get(cid)
        assert restored is not None
        assert restored.title == "finish the refactor"
        assert restored.state == "active"
    finally:
        sqlite_store.close()
