"""Worker adapters for IDE Orchestration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from .contracts import ParentTask, TaskState, WorkerProgress


@runtime_checkable
class IDEWorkerAdapter(Protocol):
    """Protocol for interacting with an IDE-based worker (Codex, Claude, Gemini)."""

    worker_id: str

    async def probe(self) -> dict[str, Any]:
        """Probe worker availability, authentication, and capability."""
        ...

    async def submit(self, task: ParentTask) -> str:
        """Submit bounded prompt to worker. Returns worker handle/session ID."""
        ...

    def observe(self, task_id: str, handle: str) -> AsyncIterator[WorkerProgress]:
        """Observe progress events emitted by the worker."""
        ...

    async def cancel(self, handle: str) -> bool:
        """Request cancellation of an active worker turn."""
        ...

    async def get_raw_result(
        self, handle: str
    ) -> tuple[TaskState, str, dict[str, Any]]:
        """Retrieve raw worker outcome prior to independent Jaeger verification."""
        ...


class DeterministicFakeWorkerAdapter:
    """Configurable deterministic fake adapter for unit testing and safe proof."""

    def __init__(
        self,
        worker_id: str = "fake_worker",
        *,
        outcome_state: TaskState = "completed",
        outcome_text: str = "Verified answer from fake worker.",
        progress_steps: tuple[str, ...] = (
            "Reading prompt",
            "Executing turn",
            "Finishing",
        ),
        available: bool = True,
        delay_seconds: float = 0.0,
    ) -> None:
        self.worker_id = worker_id
        self.outcome_state = outcome_state
        self.outcome_text = outcome_text
        self.progress_steps = progress_steps
        self.available = available
        self.delay_seconds = delay_seconds

        self.submissions: list[tuple[ParentTask, str]] = []
        self.cancelled_handles: set[str] = set()

    async def probe(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "available": self.available,
            "local": True,
            "authenticated": True,
            "transport": "test_fixture",
            "capabilities": ["read_only_enforced"],
        }

    async def submit(self, task: ParentTask) -> str:
        handle = f"{self.worker_id}:{task.task_id}:{task.idempotency_key}"
        self.submissions.append((task, handle))
        return handle

    async def observe(self, task_id: str, handle: str) -> AsyncIterator[WorkerProgress]:
        seq = 0
        yield WorkerProgress(
            task_id=task_id,
            state="submitted",
            sequence=seq,
            message=f"Submitted to {self.worker_id}",
            timestamp=time.time(),
        )
        seq += 1

        for step in self.progress_steps:
            if handle in self.cancelled_handles:
                yield WorkerProgress(
                    task_id=task_id,
                    state="failed",
                    sequence=seq,
                    message="Cancelled by orchestrator",
                    timestamp=time.time(),
                )
                return

            if self.delay_seconds > 0:
                await asyncio.sleep(self.delay_seconds)

            yield WorkerProgress(
                task_id=task_id,
                state="running",
                sequence=seq,
                message=step,
                timestamp=time.time(),
            )
            seq += 1

    async def cancel(self, handle: str) -> bool:
        self.cancelled_handles.add(handle)
        return True

    async def get_raw_result(
        self, handle: str
    ) -> tuple[TaskState, str, dict[str, Any]]:
        if handle in self.cancelled_handles:
            return "failed", "Execution cancelled", {"cancelled": True}
        return self.outcome_state, self.outcome_text, {"handle": handle}


class DelegateRuntimeAdapter:
    """Wraps an existing jaeger_agent.delegates.DelegateRuntime as an IDEWorkerAdapter."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self.worker_id = str(getattr(runtime, "runtime_id", "unknown"))
        self._handles: dict[str, Any] = {}

    def bind_store(self, path):
        from pathlib import Path
        if hasattr(self.runtime, 'receipt_root'):
            self.runtime.receipt_root = Path(path).parent / 'delegate_receipts'

    def restore_handle(self, task, handle=None):
        from jaeger_agent.delegates.contracts import DelegateHandle
        delegate = DelegateHandle(task.task_id, self.worker_id)
        directory = getattr(self.runtime, '_directory', None)
        if not callable(directory) or not (directory(delegate) / 'admission.json').exists():
            return None
        key = handle or f'{self.worker_id}:{task.task_id}:{task.idempotency_key}'
        self._handles[key] = delegate
        return key

    async def probe(self) -> dict[str, Any]:
        try:
            status = await self.runtime.probe()
            return {
                "worker_id": self.worker_id,
                "available": bool(status.available),
                "detail": str(status.detail),
                "capabilities": sorted(
                    set(status.capabilities)
                    - {
                        "existing_conversation",
                        "follow_up",
                        "reconcile",
                    }
                ),
                "transport": "cli",
                "local": bool(status.local),
            }
        except Exception as exc:  # noqa: BLE001 — external runtime probe boundary
            return {
                "worker_id": self.worker_id,
                "available": False,
                "detail": f"probe failed: {exc}",
                "capabilities": [],
                "local": True,
                "transport": "cli",
            }

    async def submit(self, task: ParentTask) -> str:
        from jaeger_agent.delegates.contracts import DelegateRequest

        status = await self.probe()
        # A CLI worker may advertise `read_only_enforced`; otherwise it cannot
        # accept a read-only task. The Gateway also rejects writable tasks.
        if task.read_only and "read_only_enforced" not in status.get("capabilities", ()):
            raise ValueError("CLI adapter cannot enforce read_only")
        missing = task.required_capabilities - set(status.get("capabilities", ()))
        if missing:
            raise ValueError(
                f"CLI adapter lacks required capabilities: {sorted(missing)}"
            )
        request = DelegateRequest(
            task_id=task.task_id,
            prompt=task.goal,
            idempotency_key=task.idempotency_key,
            workspace=task.workspace,
            timeout_seconds=max(1, int(task.budget.max_seconds)),
            sensitivity="personal",
            required_capabilities=task.required_capabilities,
            metadata=dict(task.metadata),
        )
        handle = await self.runtime.start(request)
        handle_key = f"{self.worker_id}:{task.task_id}:{task.idempotency_key}"
        self._handles[handle_key] = handle
        return handle_key

    async def observe(self, task_id: str, handle: str) -> AsyncIterator[WorkerProgress]:
        delegate_handle = self._handles.get(handle)
        seq = 0
        yield WorkerProgress(
            task_id=task_id,
            state="submitted",
            sequence=seq,
            message=f"Submitted to {self.worker_id}",
            timestamp=time.time(),
        )
        seq += 1

        if delegate_handle is None:
            yield WorkerProgress(
                task_id=task_id,
                state="unknown",
                sequence=seq,
                message="Handle not tracked by runtime adapter",
                timestamp=time.time(),
            )
            return

        try:
            async for event in self.runtime.stream(delegate_handle):
                event_type = getattr(event, "event_type", "turn.progress")
                payload = getattr(event, "payload", {})
                message = payload.get("text") or payload.get("message") or event_type
                state: TaskState = "running"
                if "block" in event_type or payload.get("blocked") is True:
                    state = "blocked"
                elif "quota" in event_type or payload.get("quota") is True:
                    state = "quota"
                elif "auth" in event_type or payload.get("auth") is True:
                    state = "auth"
                elif "approval" in event_type:
                    state = "approval"
                yield WorkerProgress(
                    task_id=task_id,
                    state=state,
                    sequence=seq,
                    message=str(message),
                    timestamp=time.time(),
                    metadata={**payload, 'delegate_sequence':getattr(event, 'sequence', seq)},
                )
                seq += 1
        except Exception as exc:  # noqa: BLE001 — preserve external runtime stream errors
            yield WorkerProgress(
                task_id=task_id,
                state="failed",
                sequence=seq,
                message=f"Stream error: {exc}",
                timestamp=time.time(),
            )

    async def cancel(self, handle: str) -> bool:
        delegate_handle = self._handles.get(handle)
        if delegate_handle is not None:
            try:
                await self.runtime.cancel(delegate_handle)
                return True
            except Exception:  # noqa: BLE001 — report unconfirmed remote cancellation
                return False
        return False

    async def get_raw_result(
        self, handle: str
    ) -> tuple[TaskState, str, dict[str, Any]]:
        delegate_handle = self._handles.get(handle)
        if delegate_handle is None:
            return "unknown", "Unknown handle", {}
        try:
            res = await self.runtime.result(delegate_handle)
            status_map: dict[str, TaskState] = {
                "completed": "completed",
                "blocked": "blocked",
                "failed": "failed",
                "cancelled": "failed",
                "quota": "quota",
                "auth": "auth",
                "approval": "approval",
                "unknown": "unknown",
            }
            state = status_map.get(res.status, "unknown")
            output = res.summary or ""
            evidence = {
                "artifacts": [getattr(a, "uri", "") for a in res.artifacts],
                "evidence": list(res.evidence),
                "metadata": dict(res.metadata),
            }
            return state, output, evidence
        except Exception as exc:  # noqa: BLE001 — external runtime result boundary
            return "failed", f"Failed to retrieve delegate result: {exc}", {}
