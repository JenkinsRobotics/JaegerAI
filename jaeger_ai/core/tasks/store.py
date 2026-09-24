"""SQLite Storage for Durable Background Work (Workstream 15).

Persisted in the Gateway session database.
Survives client disconnects, UI reloads, and host restarts.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from .models import DurableTask, TaskKind, TaskState
from collections.abc import Callable
from contextlib import closing


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
        with closing(self._get_conn()) as conn, conn:
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
        with closing(self._get_conn()) as conn, conn:
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
        with closing(self._get_conn()) as conn, conn:
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
        with closing(self._get_conn()) as conn, conn:
            rows = conn.execute(query, params).fetchall()
            return [DurableTask.from_dict(json.loads(r["task_json"])) for r in rows]

    def admit_task(self, task: DurableTask) -> tuple[DurableTask, bool]:
        """Atomic insert; a stable identity never overwrites an existing execution."""
        with closing(self._get_conn()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            old = conn.execute('SELECT task_json FROM durable_tasks WHERE task_id=?', (task.task_id,)).fetchone()
            if old:
                previous = DurableTask.from_dict(json.loads(old[0]))
                if previous.goal != task.goal or any(previous.payload.get(k) != v for k, v in task.payload.items()):
                    raise ValueError('Task identity conflicts with an admitted objective or execution configuration')
                return previous, True
            conn.execute('INSERT INTO durable_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                         (task.task_id, task.owning_agent, task.goal, task.kind.value,
                          task.state.value, json.dumps(task.to_dict()), task.created_at, task.updated_at))
        return task, False

    def update_task(self, task_id: str, change: Callable[[DurableTask], None]) -> DurableTask:
        """Serialize state transitions so cancellation cannot be overwritten by a stale worker."""
        with closing(self._get_conn()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT task_json FROM durable_tasks WHERE task_id=?', (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = DurableTask.from_dict(json.loads(row[0]))
            change(task)
            task.updated_at = time.time()
            conn.execute('UPDATE durable_tasks SET state=?, task_json=?, updated_at=? WHERE task_id=?',
                         (task.state.value, json.dumps(task.to_dict()), task.updated_at, task_id))
        return task
