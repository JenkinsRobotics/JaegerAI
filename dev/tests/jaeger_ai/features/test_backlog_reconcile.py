from __future__ import annotations

import json
import sqlite3

from jaeger_ai.features.backlog.reconcile import native_worker, record_native_handoff, reconcile
from jaeger_ai.features.backlog.store import BacklogStore


def test_native_handoff_idempotent_and_terminal(tmp_path):
    store = BacklogStore(tmp_path / "backlog.sqlite3")
    record = {"id": "h-1", "to_agent_id": "native:researcher", "task": "Research", "status": "pending_approval"}
    first = record_native_handoff(store, record)
    assert first["worker"] == "native-researcher"
    assert first["status"] == "needs_ok"
    assert record_native_handoff(store, record) == first
    record["status"] = "completed"
    done = record_native_handoff(store, record)
    assert done["id"] == first["id"]
    assert done["status"] == "done"
    assert done["handoff_result"] == "done"
    assert native_worker("tp:researcher") == ""


class GatewayStore:
    def __init__(self, path, handoffs):
        self.path, self.handoffs = path, handoffs
        with self._get_conn() as conn:
            conn.execute("CREATE TABLE agent_messages (seq INTEGER PRIMARY KEY, payload TEXT)")

    def _get_conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_handoffs(self):
        return self.handoffs


def test_reconcile_dry_run_and_repair(tmp_path):
    store = BacklogStore(tmp_path / "backlog.sqlite3")
    handoff = {"id": "h-2", "to_agent_id": "native:builder", "task": "Build", "status": "running"}
    gateway = GatewayStore(tmp_path / "gateway.sqlite3", [handoff])
    with gateway._get_conn() as conn:
        conn.execute("INSERT INTO agent_messages VALUES (?, ?)", (1, json.dumps({
            "id": "m-1", "thread": "t-1", "kind": "task", "from": "grokbot",
            "to": "ares", "title": "Hub task", "body": "Work"})))
    preview = reconcile(store, gateway)
    assert len(preview["changed"]) == 2
    assert store.list() == []
    applied = reconcile(store, gateway, apply=True)
    assert len(applied["changed"]) == 2
    assert reconcile(store, gateway, apply=True)["changed"] == []
