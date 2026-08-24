"""Bridge read/settle verbs for runs, commitments and the effect ledger."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
from jaeger_agent.memory import sqlite_store
from jaeger_ai.interfaces import bridge


def test_bridge_lists_and_settles_runtime_state(tmp_path):
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    try:
        commitment = SqliteCommitmentStore().create("finish the archive")
        run = SqliteRunStore().create(commitment.id, provider="claude")
        SqliteRunStore().transition(run.id, "active")
        SqliteRunStore().transition(run.id, "waiting_for_event", wake_key="pr:merged")
        with pytest.raises(ZeroDivisionError):
            SqliteEffectLedger().once("mail:1", "send_email", lambda: 1 / 0)

        runs = bridge._query("list_runs", {"state": "waiting_for_event"}, object())
        assert runs[0]["id"] == run.id
        assert runs[0]["wake_key"] == "pr:merged"

        commitments = bridge._query("list_commitments", {}, object())
        assert commitments[0]["title"] == "finish the archive"

        pending = bridge._query("list_effects", {}, object())
        assert pending[0]["key"] == "mail:1"
        assert pending[0]["status"] == "pending"

        ok, err = bridge._command("deliver_event", {"wake_key": "pr:merged"}, object())
        assert ok and err is None
        assert SqliteRunStore().get(run.id).state == "active"

        ok, err = bridge._command("resolve_effect", {"key": "mail:1", "result": "sent"}, object())
        assert ok and err is None
        assert SqliteEffectLedger().get("mail:1").status == "done"
    finally:
        sqlite_store.close()
