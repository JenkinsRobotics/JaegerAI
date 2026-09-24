"""Core service coordinating IDE Worker Orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from contextlib import closing
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from typing import Any

from .adapters import IDEWorkerAdapter
from .contracts import (
    OrchestrationResult,
    ParentTask,
    VerificationResult,
    WorkerProgress,
)

logger = logging.getLogger(__name__)


class IDEOrchestrationError(RuntimeError):
    """Base error for IDE orchestration failures."""


class WorkerUnavailableError(IDEOrchestrationError):
    """Raised when an assigned worker is not registered or unavailable."""


class DuplicateSubmissionConflict(IDEOrchestrationError):
    """Raised when re-submitting an active task with divergent parameters."""


class IDEOrchestrationService:
    """Worker coordination with Gateway-owned durable admission and result receipts."""

    def __init__(self, adapters: dict[str, IDEWorkerAdapter] | None = None) -> None:
        self._db_path = None
        self._snapshots: dict[str, str] = {}
        self._adapters = dict(adapters or {})
        self._idempotency_records: dict[str, dict[str, Any]] = {}
        self._tasks: dict[str, dict[str, Any]] = {}
        self._active_executions: dict[str, dict[str, Any]] = {}
        self._progress_hooks: list[Callable[[WorkerProgress], None]] = []

    def bind_store(self, path) -> None:
        """Use the owner database. A lost process never erases accepted task identity."""
        self._db_path = str(path)
        for adapter in self._adapters.values():
            binder = getattr(adapter, 'bind_store', None)
            if callable(binder):
                binder(path)
        with closing(sqlite3.connect(self._db_path)) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS orchestration_tasks (task_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL, snapshot TEXT NOT NULL, record TEXT NOT NULL)')
            rows = conn.execute('SELECT task_id, snapshot, record FROM orchestration_tasks').fetchall()
        for task_id, snapshot, record in rows:
            data = json.loads(record)
            if data.get('result') is None:
                data['state'] = 'unknown'
                data['result'] = dict(task_id=task_id, worker_id=data['worker'], state='unknown', output='Owner restarted; reconcile the worker before resubmission',
                    verified=False, reason='No terminal worker receipt', checked_artifacts=[], budget_used_seconds=0,
                    evidence={'delivery_unknown':True, 'handle':data.get('handle')})
            self._tasks[task_id] = data
            self._snapshots[task_id] = snapshot
            self._persist(task_id)

    def _persist(self, task_id):
        if self._db_path is None:
            return
        row = self._tasks[task_id]
        with closing(sqlite3.connect(self._db_path, timeout=10)) as conn, conn:
            conn.execute('INSERT INTO orchestration_tasks VALUES (?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET record=excluded.record',
                         (task_id, row['idempotency_key'], self._snapshots[task_id], json.dumps(row)))

    @staticmethod
    def _restored_result(data):
        return OrchestrationResult(data['task_id'], data['worker_id'], data['state'], data['output'],
            VerificationResult(data['verified'], data['reason'], tuple(data.get('checked_artifacts') or [])),
            data.get('budget_used_seconds', 0), data.get('evidence') or {})

    def register_adapter(self, adapter: IDEWorkerAdapter) -> None:
        self._adapters[adapter.worker_id] = adapter
        binder = getattr(adapter, 'bind_store', None)
        if self._db_path and callable(binder):
            binder(self._db_path)

    def resume_pending(self):
        """Reattach persistent worker receipts, without another submit call."""
        from pathlib import Path
        from .contracts import TaskBudget
        for task_id, row in self._tasks.items():
            if row.get('state') != 'unknown' or task_id in self._active_executions:
                continue
            adapter = self._adapters.get(row['worker'])
            restore = getattr(adapter, 'restore_handle', None)
            if not callable(restore):
                continue
            data = json.loads(self._snapshots[task_id])
            data['workspace'] = Path(data['workspace']) if data.get('workspace') else None
            data['budget'] = TaskBudget(**data['budget'])
            data['required_capabilities'] = frozenset(data['required_capabilities'])
            task = ParentTask(**data)
            handle = restore(task, row.get('handle'))
            if handle is None:
                continue
            execution = {'cancelled':False, 'started':False, 'handle':handle,
                         'submit_started':True, 'recovered':True, 'operation':None}
            row['result'] = None
            row['state'] = 'running'
            self._persist(task_id)
            operation = asyncio.create_task(self._execute(task, adapter, execution, None))
            execution['operation'] = operation
            self._active_executions[task_id] = execution
            self._idempotency_records[task.idempotency_key] = {'snapshot':self._snapshots[task_id], 'operation':operation}

    def unregister_adapter(self, worker_id: str) -> None:
        self._adapters.pop(worker_id, None)

    async def list_workers(self) -> list[dict[str, Any]]:
        workers = []
        for worker_id, adapter in sorted(self._adapters.items()):
            try:
                workers.append(await adapter.probe())
            except Exception as exc:  # noqa: BLE001 — independent adapter availability
                workers.append(
                    {
                        "worker_id": worker_id,
                        "available": False,
                        "detail": f"probe failed: {exc}",
                        "capabilities": [],
                        "local": True,
                    }
                )
        return workers

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Read the in-memory projection of the durable owner record."""
        return self._tasks.get(task_id)

    def add_progress_hook(self, hook: Callable[[WorkerProgress], None]) -> None:
        self._progress_hooks.append(hook)

    def _notify_progress(self, progress: WorkerProgress) -> None:
        record = self._tasks.get(progress.task_id)
        if record is not None:
            progress = replace(progress, sequence=len(record["progress"]))
            record["state"] = progress.state
            record["progress"].append(asdict(progress))
            self._persist(progress.task_id)
        for hook in self._progress_hooks:
            try:
                hook(progress)
            except Exception:
                logger.debug("Progress hook error", exc_info=True)

    async def cancel_task(self, task_id: str) -> bool:
        execution = self._active_executions.get(task_id)
        if execution is None or self._tasks[task_id]["result"] is not None:
            return False
        execution["cancelled"] = True
        # Before the coroutine starts, its own flag check must finalize the result.
        if execution["started"]:
            execution["operation"].cancel()
        return True

    async def cancel_all(self, *, timeout_seconds: float = 2.0) -> tuple[str, ...]:
        """Cancel and attempt a bounded join before the owner releases its lease.

        Cancelling only the outer asyncio task bypasses the adapter cancellation
        boundary and can orphan a delegate subprocess. A cleanup timeout remains
        explicitly unknown so process shutdown can finish without inferring remote
        cancellation.
        """
        active = [
            (task_id, execution, execution["operation"])
            for task_id, execution in tuple(self._active_executions.items())
            if execution.get("operation") is not None
            and self._tasks.get(task_id, {}).get("result") is None
        ]
        for task_id, _execution, _operation in active:
            await self.cancel_task(task_id)
        if not active:
            return ()

        _done, pending = await asyncio.wait(
            [operation for _task_id, _execution, operation in active],
            timeout=max(0.0, timeout_seconds),
        )
        unresolved: list[str] = []
        for task_id, execution, operation in active:
            if operation not in pending:
                continue
            unresolved.append(task_id)
            result = OrchestrationResult(
                task_id,
                self._tasks[task_id]["worker"],
                "unknown",
                "Shutdown timed out while confirming worker cancellation",
                VerificationResult(False, "Worker cancellation was not confirmed"),
                0.0,
                {
                    "cancelled": True,
                    "shutdown_timeout": True,
                    "worker_cancel_confirmed": False,
                },
            )
            execution["forced_result"] = result
            self._tasks[task_id]["result"] = {
                "task_id": result.task_id,
                "worker_id": result.worker_id,
                "state": result.state,
                "output": result.output,
                "verified": False,
                "reason": result.verification.reason,
                "checked_artifacts": [],
                "budget_used_seconds": 0.0,
                "evidence": result.evidence,
            }
            self._notify_progress(WorkerProgress(task_id, "unknown", 0, result.output))
            operation.cancel()
        return tuple(unresolved)

    @staticmethod
    def _snapshot(task: ParentTask) -> str:
        data = asdict(task)
        data["workspace"] = str(task.workspace) if task.workspace is not None else None
        data["required_capabilities"] = sorted(task.required_capabilities)
        return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

    async def execute_parent_task(
        self,
        task: ParentTask,
        *,
        verifier: Callable[[str, dict[str, Any]], VerificationResult] | None = None,
    ) -> OrchestrationResult:
        operation, _replayed = self.admit_parent_task(task, verifier=verifier)
        return await asyncio.shield(operation)

    def admit_parent_task(
        self,
        task: ParentTask,
        *,
        verifier: Callable[[str, dict[str, Any]], VerificationResult] | None = None,
    ) -> tuple[asyncio.Future[OrchestrationResult], bool]:
        """Synchronously reserve an immutable request before HTTP acknowledges it.

        Returns the tracked operation and whether this is an identical replay.
        Admission is persisted before dispatch; replay survives owner restart.
        """
        snapshot = self._snapshot(task)
        restored = next((r for r in self._tasks.values() if r['idempotency_key'] == task.idempotency_key), None)
        if restored is not None and task.idempotency_key not in self._idempotency_records:
            if self._snapshots.get(restored['task_id']) != snapshot:
                raise DuplicateSubmissionConflict('Idempotency key conflicts with durable accepted request')
            future = asyncio.get_running_loop().create_future()
            future.set_result(self._restored_result(restored['result']))
            return future, True
        existing = self._idempotency_records.get(task.idempotency_key)
        if existing is not None:
            if existing["snapshot"] != snapshot:
                raise DuplicateSubmissionConflict(
                    "Idempotency key conflicts with accepted request"
                )
            return existing["operation"], True
        if task.task_id in self._tasks:
            raise DuplicateSubmissionConflict(
                "Task ID already belongs to another accepted request"
            )
        adapter = self._adapters.get(task.assigned_worker)
        if adapter is None:
            raise WorkerUnavailableError(
                f"Worker {task.assigned_worker!r} is not registered"
            )

        # Freeze nested metadata and reserve identity before any await. Concurrent
        # calls on the Gateway event loop join the same operation.
        task = replace(task, metadata=json.loads(snapshot)["metadata"])
        self._tasks[task.task_id] = {
            "task_id": task.task_id,
            "goal": task.goal,
            "worker": task.assigned_worker,
            "idempotency_key": task.idempotency_key,
            "read_only": task.read_only,
            "state": "queued",
            "progress": [],
            "result": None,
        }
        execution = {
            "cancelled": False,
            "started": False,
            "handle": None,
            "submit_started": False,
            "operation": None,
        }
        self._snapshots[task.task_id] = snapshot
        self._persist(task.task_id)
        self._active_executions[task.task_id] = execution
        operation = asyncio.create_task(
            self._execute(task, adapter, execution, verifier)
        )
        execution["operation"] = operation
        self._idempotency_records[task.idempotency_key] = {
            "snapshot": snapshot,
            "operation": operation,
        }
        operation.add_done_callback(lambda done: self._record_early_cancel(task, done))
        return operation, False

    def _record_early_cancel(self, task: ParentTask, operation: asyncio.Task) -> None:
        """Owner shutdown may cancel a task before its coroutine can run."""
        if not operation.cancelled() or self._tasks[task.task_id]["result"] is not None:
            return
        result = OrchestrationResult(
            task.task_id,
            task.assigned_worker,
            "failed",
            "Task cancelled before execution",
            VerificationResult(False, "No execution or verification occurred"),
            0.0,
            {"cancelled": True, "submitted": False},
        )
        self._tasks[task.task_id]["result"] = {
            "task_id": result.task_id,
            "worker_id": result.worker_id,
            "state": result.state,
            "output": result.output,
            "verified": False,
            "reason": result.verification.reason,
            "checked_artifacts": [],
            "budget_used_seconds": 0.0,
            "evidence": result.evidence,
        }
        self._notify_progress(WorkerProgress(task.task_id, "failed", 0, result.output))
        self._active_executions.pop(task.task_id, None)
        replay = asyncio.get_running_loop().create_future()
        replay.set_result(result)
        self._idempotency_records[task.idempotency_key]["operation"] = replay

    async def _execute(self, task, adapter, execution, verifier) -> OrchestrationResult:
        started = time.monotonic()
        execution["started"] = True
        state, output, evidence = "queued", "", {}
        try:
            self._notify_progress(
                WorkerProgress(
                    task.task_id, "queued", 0, f"Queued for {task.assigned_worker}"
                )
            )
            if execution["cancelled"]:
                raise asyncio.CancelledError
            # Covers silent probe/submit/stream/result, not only event boundaries.
            async with asyncio.timeout(task.budget.max_seconds):
                if execution.get('recovered'):
                    previous = max((p.get('metadata', {}).get('delegate_sequence', -1)
                                    for p in self._tasks[task.task_id]['progress']), default=-1)
                    async for progress in adapter.observe(task.task_id, execution['handle']):
                        if execution['cancelled']:
                            raise asyncio.CancelledError
                        if progress.metadata.get('delegate_sequence', -1) > previous:
                            self._notify_progress(progress)
                    state, output, evidence = await adapter.get_raw_result(execution['handle'])
                else:
                    status = await adapter.probe()
                    if not status.get("available", False):
                        reason = status.get("state")
                        state = (
                            reason if reason in {"quota", "auth", "blocked"} else "blocked"
                        )
                        output = str(status.get("detail") or "Worker offline")
                    else:
                        required = set(task.required_capabilities)
                        if task.read_only:
                            required.add("read_only_enforced")
                        missing = required - set(status.get("capabilities", ()))
                        if missing:
                            state = "blocked"
                            output = (
                                f"Worker lacks required capabilities: {sorted(missing)}"
                            )
                        else:
                            execution["submit_started"] = True
                            self._tasks[task.task_id]["submit_started"] = True
                            self._persist(task.task_id)
                            execution["handle"] = await adapter.submit(task)
                            self._tasks[task.task_id]["handle"] = execution["handle"]
                            self._persist(task.task_id)
                            async for progress in adapter.observe(
                                task.task_id, execution["handle"]
                            ):
                                if execution["cancelled"]:
                                    raise asyncio.CancelledError
                                self._notify_progress(progress)
                            if execution["cancelled"]:
                                raise asyncio.CancelledError
                            state, output, evidence = await adapter.get_raw_result(
                                execution["handle"]
                            )
        except asyncio.CancelledError:
            state, output = "failed", "Task cancelled by orchestrator"
            evidence = {"cancelled": True}
            if execution["submit_started"] and execution["handle"] is None:
                state = "unknown"
                evidence["delivery_unknown"] = True
        except TimeoutError:
            state, output = (
                "blocked",
                f"Execution exceeded {task.budget.max_seconds}s time budget",
            )
            evidence = {"timed_out": True}
            if execution["submit_started"] and execution["handle"] is None:
                state = "unknown"
                evidence["delivery_unknown"] = True
        except Exception as exc:  # noqa: BLE001 — record adapter failure as task outcome
            state, output = (
                "failed",
                f"Worker execution exception: {type(exc).__name__}: {exc}",
            )
            evidence["execution_failed"] = True
            if execution["submit_started"] and execution["handle"] is None:
                state = "unknown"
                evidence["delivery_unknown"] = True

        # Cleanup has a separate one-second bound; confirmation is not assumed.
        if (
            execution["cancelled"]
            or evidence.get("timed_out")
            or evidence.get("execution_failed")
        ) and execution["handle"]:
            try:
                evidence["worker_cancel_confirmed"] = bool(
                    await asyncio.wait_for(
                        adapter.cancel(execution["handle"]), timeout=1.0
                    )
                )
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 — cancellation is unconfirmed
                evidence["worker_cancel_confirmed"] = False

        forced_result = execution.get("forced_result")
        if forced_result is not None:
            self._active_executions.pop(task.task_id, None)
            return forced_result

        verification = VerificationResult(False, "No independent verifier was run")
        if state != "completed":
            verification = VerificationResult(
                False, f"Worker ended in non-completed state: {state}"
            )
        elif verifier is not None:
            try:
                verification = verifier(output, evidence)
            except Exception as exc:  # noqa: BLE001 — preserve worker output on verifier failure
                verification = VerificationResult(
                    False, f"Verifier failed: {type(exc).__name__}"
                )
        result = OrchestrationResult(
            task.task_id,
            task.assigned_worker,
            state,
            output,
            verification,
            round(time.monotonic() - started, 3),
            evidence,
        )
        self._tasks[task.task_id]["result"] = {
            "task_id": result.task_id,
            "worker_id": result.worker_id,
            "state": result.state,
            "output": result.output,
            "verified": result.verification.verified,
            "reason": result.verification.reason,
            "checked_artifacts": list(result.verification.checked_artifacts),
            "budget_used_seconds": result.budget_used_seconds,
            "evidence": result.evidence,
        }
        self._notify_progress(WorkerProgress(task.task_id, state, 0, output))
        self._active_executions.pop(task.task_id, None)
        return result


def create_default_orchestration_service() -> IDEOrchestrationService:
    """Instantiate default IDEOrchestrationService with discovered delegate runtimes."""
    from .adapters import DelegateRuntimeAdapter

    service = IDEOrchestrationService()

    try:
        from jaeger_agent.delegates.codex.runtime import create_runtime as create_codex

        service.register_adapter(DelegateRuntimeAdapter(create_codex()))
    except Exception as exc:  # noqa: BLE001 — optional runtime registration
        logger.debug("Codex delegate runtime not registered: %s", exc)

    try:
        from jaeger_agent.delegates.claude.runtime import (
            create_runtime as create_claude,
        )

        service.register_adapter(DelegateRuntimeAdapter(create_claude()))
    except Exception as exc:  # noqa: BLE001 — optional runtime registration
        logger.debug("Claude delegate runtime not registered: %s", exc)

    try:
        from jaeger_agent.delegates.gemini.runtime import (
            create_runtime as create_gemini,
        )

        service.register_adapter(DelegateRuntimeAdapter(create_gemini()))
    except Exception as exc:  # noqa: BLE001 — optional runtime registration
        logger.debug("Gemini delegate runtime not registered: %s", exc)

    return service
