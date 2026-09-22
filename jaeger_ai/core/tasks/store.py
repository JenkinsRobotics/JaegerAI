"""SQLite Storage for Durable Background Work (Workstream 15).

Persisted in <state_root>/durable_tasks.sqlite3.
Survives client disconnects, UI reloads, and host restarts.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .models import DurableTask, TaskKind, TaskState


class SqliteDurableTaskStore:
    """Persistent SQLite store for durable tasks and automations."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_tasks (
                    task_id TEXT PRIMARY KEY,
                    owning_agent TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state ON durable_tasks(state);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON durable_tasks(owning_agent);")

    def save_task(self, task: DurableTask) -> None:
        task.updated_at = time.time()
        payload = json.dumps(task.to_dict())
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO durable_tasks (task_id, owning_agent, goal, kind, state, task_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    owning_agent=excluded.owning_agent,
                    goal=excluded.goal,
                    kind=excluded.kind,
                    state=excluded.state,
                    task_json=excluded.task_json,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.owning_agent,
                    task.goal,
                    task.kind.value,
                    task.state.value,
                    payload,
                    task.created_at,
                    task.updated_at,
                ),
            )

    def get_task(self, task_id: str) -> DurableTask | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT task_json FROM durable_tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return DurableTask.from_dict(json.loads(row["task_json"]))

    def list_tasks(
        self,
        *,
        owning_agent: str | None = None,
        state: TaskState | str | None = None,
        kind: TaskKind | str | None = None,
    ) -> list[DurableTask]:
        query = "SELECT task_json FROM durable_tasks WHERE 1=1"
        params: list[Any] = []

        if owning_agent:
            query += " AND owning_agent = ?"
            params.append(owning_agent)
        if state:
            s_val = state.value if isinstance(state, TaskState) else str(state)
            query += " AND state = ?"
            params.append(s_val)
        if kind:
            k_val = kind.value if isinstance(kind, TaskKind) else str(kind)
            query += " AND kind = ?"
            params.append(k_val)

        query += " ORDER BY created_at DESC"
        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [DurableTask.from_dict(json.loads(r["task_json"])) for r in rows]

    def recover_orphaned_tasks(self) -> list[DurableTask]:
        """Find active tasks from crashed/interrupted sessions and mark for recovery."""
        orphaned = []
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT task_json FROM durable_tasks WHERE state = ?",
                (TaskState.RUNNING.value,),
            ).fetchall()
            for r in rows:
                task = DurableTask.from_dict(json.loads(r["task_json"]))
                # Reset to queued with incremented retry
                task.state = TaskState.QUEUED
                task.retry_policy.current_retries += 1
                self.save_task(task)
                orphaned.append(task)
        return orphaned
