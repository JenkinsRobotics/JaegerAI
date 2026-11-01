"""Durable A2A TaskStore backed by SQLite, correlated to Jaeger's Gateway.

Replaces the SDK ``InMemoryTaskStore`` (lost on restart). This is NOT a second
executor or queue: execution, approvals and cancellation stay with the
Gateway. The A2A task id is the Gateway request id (the executor passes it as
the bridge ``turn_id``, which the bridge hands to the Gateway as
``request_id``), and ``contextId`` maps to the ``a2a:<contextId>`` session /
thread. This store only persists the A2A projection of that request.

On load, a task that was non-terminal when the process stopped is marked
FAILED with ``jaeger.execution_unknown`` so GetTask never reports a stale
WORKING: the Gateway request with the same id is the authority on what ran.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

from a2a.server.context import ServerCallContext
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks.inmemory_task_store import _InMemoryTaskStoreImpl
from a2a.server.tasks.task_store import TaskStore
from a2a.types import Message, Part, Role, Task, TaskState, TaskStatus

TERMINAL = frozenset({
    TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED, TaskState.TASK_STATE_REJECTED,
})


def default_db_path() -> Path:
    from jaeger_ai.features.agentgateway.constants import jaeger_home

    return jaeger_home() / "a2a" / "tasks.sqlite3"


class LedgerTaskStore(TaskStore):
    def __init__(self, path: Path | str | None = None, owner_resolver=resolve_user_scope) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._owner = owner_resolver
        self._mem = _InMemoryTaskStoreImpl(owner_resolver=lambda ctx: ctx)  # owner passed explicitly
        self._db_lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS a2a_tasks (owner TEXT NOT NULL, task_id TEXT NOT NULL, "
            "context_id TEXT, state INTEGER, updated_at REAL, task BLOB NOT NULL, "
            "PRIMARY KEY (owner, task_id))")
        self._conn.commit()
        self._load()

    def _load(self) -> None:
        rows = self._conn.execute("SELECT owner, task FROM a2a_tasks").fetchall()
        for owner, blob in rows:
            task = Task()
            task.ParseFromString(blob)
            if task.status.state not in TERMINAL:
                # A2A wire projection only (a2a.types.TaskState), not a Jaeger
                # durable task state: Jaeger's own state stays with the Gateway.
                status = TaskStatus(
                    state=TaskState.TASK_STATE_FAILED,
                    message=Message(
                        role=Role.ROLE_AGENT, message_id=f"restart-{task.id}",
                        parts=[Part(text=("The A2A server restarted while this task was active. "
                                          f"Jaeger request {task.id} is the authority on what ran; "
                                          "check it in Jaeger's Activity/Approvals."))]))
                status.timestamp.GetCurrentTime()
                task.status.CopyFrom(status)
                task.metadata.update({"jaeger.execution_unknown": True})
                self._write(owner, task)
            self._mem.tasks.setdefault(owner, {})[task.id] = task

    def _write(self, owner: str, task: Task) -> None:
        with self._db_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO a2a_tasks VALUES (?,?,?,?,?,?)",
                (owner, task.id, task.context_id, int(task.status.state), time.time(),
                 task.SerializeToString()))
            self._conn.commit()

    def _delete(self, owner: str, task_id: str) -> None:
        with self._db_lock:
            self._conn.execute("DELETE FROM a2a_tasks WHERE owner=? AND task_id=?", (owner, task_id))
            self._conn.commit()

    async def save(self, task: Task, context: ServerCallContext) -> None:
        owner = self._owner(context)
        await asyncio.to_thread(self._write, owner, task)
        await self._mem.save(task, owner)

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        return await self._mem.get(task_id, self._owner(context))

    async def list(self, params, context: ServerCallContext):
        return await self._mem.list(params, self._owner(context))

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        owner = self._owner(context)
        await asyncio.to_thread(self._delete, owner, task_id)
        await self._mem.delete(task_id, owner)

    def close(self) -> None:
        with self._db_lock:
            self._conn.close()
