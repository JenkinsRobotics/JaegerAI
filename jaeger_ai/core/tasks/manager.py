"""Durable Task Manager and Background Worker Engine (Workstream 15).

Coordinates background execution of durable tasks, decoupled from client connections.
Survives client disconnects and recovers gracefully across process restarts.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid

from .models import (
    DurableTask,
    NotificationPolicy,
    RetryPolicy,
    TaskKind,
    TaskRunRecord,
    TaskState,
)
from .store import SqliteDurableTaskStore

logger = logging.getLogger("jaeger.core.tasks.manager")


class DurableTaskManager:
    """Coordinates resilient background task execution and restart recovery."""

    def __init__(
        self,
        store: SqliteDurableTaskStore,
        max_workers: int = 4,
    ) -> None:
        self.store = store
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="durable_task")
        self._futures: dict[str, Future[Any]] = {}
        self._lock = threading.RLock()

    def submit_task(
        self,
        goal: str,
        owning_agent: str = "agent:jaeger",
        *,
        kind: TaskKind = TaskKind.BACKGROUND_WORK,
        payload: dict[str, Any] | None = None,
        retry_policy: RetryPolicy | None = None,
        notification_policy: NotificationPolicy | None = None,
        provenance: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> DurableTask:
        """Admit a new durable task into the persistent store."""
        tid = task_id or f"tsk_{uuid.uuid4().hex[:12]}"
        task = DurableTask(
            task_id=tid,
            owning_agent=owning_agent,
            goal=goal.strip(),
            kind=kind,
            state=TaskState.QUEUED,
            payload=dict(payload or {}),
            retry_policy=retry_policy or RetryPolicy(),
            notification_policy=notification_policy or NotificationPolicy(),
            provenance=dict(provenance or {}),
            created_at=time.time(),
        )
        self.store.save_task(task)
        logger.info("Admitted durable task %s (%s) for %s", tid, goal[:60], owning_agent)
        return task

    def start_background_task(
        self,
        task_id: str,
        execution_fn: Callable[[DurableTask], Any],
    ) -> Future[Any]:
        """Dispatch a durable task to execute asynchronously in the background pool.

        Client disconnect does NOT cancel or interrupt this execution.
        """
        with self._lock:
            task = self.store.get_task(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")

            if task.state == TaskState.CANCELLED:
                raise RuntimeError(f"Task {task_id} is cancelled")

            run_id = f"run_{uuid.uuid4().hex[:10]}"
            run_rec = TaskRunRecord(run_id=run_id, started_at=time.time(), status="running")
            task.run_history.append(run_rec)
            task.state = TaskState.RUNNING
            self.store.save_task(task)

            future = self._executor.submit(self._run_wrapper, task_id, run_id, execution_fn)
            self._futures[task_id] = future
            return future

    def _run_wrapper(
        self,
        task_id: str,
        run_id: str,
        execution_fn: Callable[[DurableTask], Any],
    ) -> Any:
        task = self.store.get_task(task_id)
        if not task:
            return None

        # Check if already cancelled
        if task.state == TaskState.CANCELLED:
            return None

        result = None
        error_msg = None
        status = "completed"

        try:
            result = execution_fn(task)
            task.result = result
            task.state = TaskState.COMPLETED
        except Exception as exc:
            logger.error("Background task %s failed: %s", task_id, exc)
            error_msg = str(exc)
            status = "failed"
            task.error = error_msg
            if task.retry_policy.can_retry():
                task.state = TaskState.QUEUED
                task.retry_policy.current_retries += 1
            else:
                task.state = TaskState.FAILED

        # Update run record
        for r in task.run_history:
            if r.run_id == run_id:
                r.completed_at = time.time()
                r.status = status
                r.error = error_msg

        self.store.save_task(task)
        return result

    def cancel_task(self, task_id: str, reason: str = "Cancelled by user") -> bool:
        """Cancel a queued or running durable task."""
        with self._lock:
            task = self.store.get_task(task_id)
            if not task or task.is_terminal:
                return False

            task.state = TaskState.CANCELLED
            task.cancellation = reason
            self.store.save_task(task)

            # Cancel future if still pending
            fut = self._futures.get(task_id)
            if fut and not fut.done():
                fut.cancel()

            logger.info("Cancelled durable task %s: %s", task_id, reason)
            return True

    def get_task(self, task_id: str) -> DurableTask | None:
        return self.store.get_task(task_id)

    def recover_and_resume_all(
        self,
        resumer_fn: Callable[[DurableTask], Any] | None = None,
    ) -> list[DurableTask]:
        """Recover tasks left uncompleted from a previous crash/restart and resume them."""
        orphans = self.store.recover_orphaned_tasks()
        logger.info("Recovered %d orphaned tasks from previous process run", len(orphans))
        if callable(resumer_fn):
            for t in orphans:
                self.start_background_task(t.task_id, resumer_fn)
        return orphans

    def shutdown(self, wait: bool = False) -> None:
        """Shut down the background worker thread pool."""
        self._executor.shutdown(wait=wait)

