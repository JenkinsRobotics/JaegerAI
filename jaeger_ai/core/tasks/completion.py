"""The one authoritative task-state transition.

Workers return evidence. They do not mark a task completed_verified.
A bare "success" is not evidence. Legacy ``completed`` stays a worker
status and cannot be written through this function.
"""
from __future__ import annotations

from typing import Any

from jaeger_ai.core.tasks.models import DurableTask, TaskState

AUTHORITATIVE = frozenset({
    TaskState.COMPLETED_VERIFIED,
    TaskState.NEEDS_OWNER,
    TaskState.BLOCKED,
    TaskState.FAILED,
    TaskState.CANCELLED,
    TaskState.QUEUED,
    TaskState.RUNNING,
    TaskState.PAUSED,
})


class CompletionError(ValueError):
    pass


def authoritative_transition(
    task: DurableTask,
    state: TaskState,
    *,
    evidence: Any = None,
    error: str | None = None,
) -> DurableTask:
    if state not in AUTHORITATIVE:
        raise CompletionError(f"not an authoritative state: {state!r}")
    if state == TaskState.COMPLETED_VERIFIED and not _evidence_ok(evidence):
        raise CompletionError("completed_verified requires evidence")
    task.state = state
    task.error = error
    task.payload = dict(task.payload)
    task.payload["verification"] = evidence if evidence is not None else ""
    return task


def _evidence_ok(evidence: Any) -> bool:
    if evidence is None or evidence in ("", [], {}):
        return False
    if isinstance(evidence, str) and evidence.strip().lower() in {"ok", "success", "completed", "done"}:
        return False
    if isinstance(evidence, dict) and set(evidence.keys()) <= {"ok", "success", "status"}:
        return False
    return True
