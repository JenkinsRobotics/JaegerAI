"""Canonical Work Lifecycle & State Machine (UPAA Workstream 2).

Establishes exactly one canonical lifecycle for all agent work across:
Gateway, EntityRuntime, JaegerAgent, Bridge, CLI, Background Tasks, and Scheduled Jobs.

Target State Machine:
    CREATED
    -> QUEUED
    -> RUNNING
    -> WAITING_FOR_APPROVAL
    -> RUNNING
    -> VERIFYING
    -> COMPLETED

    or

    -> FAILED
    -> CANCELLED
    -> INTERRUPTED
    -> RECOVERABLE

Invariants:
- One request ID maps to one durable run.
- One run owns its lifecycle.
- Cancellation is deterministic.
- Approval/resume is durable (suspended run state, not an in-memory blocked thread).
- Process death (SIGKILL/restart) leaves runs in INTERRUPTED/RECOVERABLE, not undefined state.
- Effects are registered in EffectLedger, preventing duplicate execution on recovery.
"""

from __future__ import annotations

import logging
import os
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("jaeger.runtime.lifecycle")


class WorkState(str, Enum):
    """Canonical states for agent work execution."""
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_EVENT = "waiting_for_event"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    RECOVERABLE = "recoverable"


# Legacy state aliases for backward compatibility across subsystems
_STATE_ALIASES: dict[str, WorkState] = {
    "created": WorkState.CREATED,
    "queued": WorkState.QUEUED,
    "active": WorkState.RUNNING,
    "running": WorkState.RUNNING,
    "waiting_for_user": WorkState.WAITING_FOR_APPROVAL,
    "waiting_for_approval": WorkState.WAITING_FOR_APPROVAL,
    "waiting_for_event": WorkState.WAITING_FOR_EVENT,
    "verifying": WorkState.VERIFYING,
    "completed": WorkState.COMPLETED,
    "failed": WorkState.FAILED,
    "cancelled": WorkState.CANCELLED,
    "blocked": WorkState.INTERRUPTED,
    "interrupted": WorkState.INTERRUPTED,
    "recoverable": WorkState.RECOVERABLE,
    "paused": WorkState.WAITING_FOR_APPROVAL,
}

TERMINAL_STATES = frozenset({
    WorkState.COMPLETED,
    WorkState.CANCELLED,
    WorkState.FAILED,
})

RESUMABLE_STATES = frozenset({
    WorkState.WAITING_FOR_APPROVAL,
    WorkState.WAITING_FOR_EVENT,
    WorkState.INTERRUPTED,
    WorkState.RECOVERABLE,
})

ALLOWED_TRANSITIONS: dict[WorkState, frozenset[WorkState]] = {
    WorkState.CREATED: frozenset({
        WorkState.QUEUED,
        WorkState.RUNNING,
        WorkState.CANCELLED,
    }),
    WorkState.QUEUED: frozenset({
        WorkState.RUNNING,
        WorkState.CANCELLED,
        WorkState.INTERRUPTED,
    }),
    WorkState.RUNNING: frozenset({
        WorkState.WAITING_FOR_APPROVAL,
        WorkState.WAITING_FOR_EVENT,
        WorkState.VERIFYING,
        WorkState.COMPLETED,
        WorkState.FAILED,
        WorkState.CANCELLED,
        WorkState.INTERRUPTED,
    }),
    WorkState.WAITING_FOR_APPROVAL: frozenset({
        WorkState.RUNNING,
        WorkState.CANCELLED,
        WorkState.FAILED,
        WorkState.INTERRUPTED,
    }),
    WorkState.WAITING_FOR_EVENT: frozenset({
        WorkState.RUNNING,
        WorkState.CANCELLED,
        WorkState.FAILED,
        WorkState.INTERRUPTED,
    }),
    WorkState.VERIFYING: frozenset({
        WorkState.COMPLETED,
        WorkState.RUNNING,
        WorkState.FAILED,
        WorkState.CANCELLED,
        WorkState.INTERRUPTED,
    }),
    WorkState.INTERRUPTED: frozenset({
        WorkState.RECOVERABLE,
        WorkState.FAILED,
        WorkState.CANCELLED,
        WorkState.RUNNING,
    }),
    WorkState.RECOVERABLE: frozenset({
        WorkState.RUNNING,
        WorkState.QUEUED,
        WorkState.CANCELLED,
        WorkState.FAILED,
    }),
    WorkState.COMPLETED: frozenset(),
    WorkState.CANCELLED: frozenset(),
    WorkState.FAILED: frozenset({
        WorkState.RECOVERABLE,
    }),
}


class LifecycleTransitionError(RuntimeError):
    """Raised when an invalid state transition is attempted."""


def normalize_state(raw: str | WorkState) -> WorkState:
    """Normalize any string or enum to a canonical WorkState."""
    if isinstance(raw, WorkState):
        return raw
    cleaned = str(raw).strip().lower()
    if cleaned in _STATE_ALIASES:
        return _STATE_ALIASES[cleaned]
    try:
        return WorkState(cleaned)
    except ValueError:
        raise LifecycleTransitionError(f"Unknown work state: {raw!r}")


def validate_transition(
    run_id: str,
    current: str | WorkState,
    target: str | WorkState,
) -> tuple[WorkState, WorkState]:
    """Validate that transition from current to target state is legally permitted."""
    src = normalize_state(current)
    dst = normalize_state(target)
    if dst not in ALLOWED_TRANSITIONS.get(src, frozenset()):
        raise LifecycleTransitionError(
            f"Illegal run lifecycle transition for {run_id!r}: cannot move from {src.value} to {dst.value}"
        )
    return src, dst


class RunLifecycleCoordinator:
    """High-level coordinator managing the lifecycle of durable runs."""

    def __init__(self, run_store: Any | None = None) -> None:
        self._store = run_store

    def _get_store(self) -> Any:
        if self._store is not None:
            return self._store
        from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
        self._store = SqliteRunStore()
        return self._store

    def create_run(
        self,
        commitment_id: str,
        *,
        request_id: str | None = None,
        provider: str | None = None,
        owner_pid: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Create a new run in CREATED state."""
        store = self._get_store()
        pid = owner_pid if owner_pid is not None else os.getpid()
        run = store.create(
            commitment_id=commitment_id,
            provider=provider,
            owner_pid=pid,
            payload={**(payload or {}), "request_id": request_id},
        )
        return run

    def advance(
        self,
        run_id: str,
        target_state: str | WorkState,
        *,
        reason: str | None = None,
        wake_key: str | None = None,
    ) -> Any:
        """Advance run to a target state, enforcing transition rules."""
        store = self._get_store()
        run = store.get(run_id)
        if run is None:
            raise LifecycleTransitionError(f"Run {run_id!r} does not exist")
        src, dst = validate_transition(run_id, run.state, target_state)
        # Transition via underlying store (accepts mapped string values)
        return store.transition(
            run_id,
            dst.value,
            reason=reason,
            wake_key=wake_key,
        )

    def suspend_for_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        reason: str = "operator_approval_required",
    ) -> Any:
        """Transition run to WAITING_FOR_APPROVAL keyed by approval ID."""
        wake_key = f"approval:{approval_id}"
        return self.advance(
            run_id,
            WorkState.WAITING_FOR_APPROVAL,
            reason=reason,
            wake_key=wake_key,
        )

    def resume_from_approval(
        self,
        approval_id: str,
        *,
        approved: bool = True,
        owner_pid: int | None = None,
    ) -> list[Any]:
        """Resume any runs waiting for the given approval."""
        store = self._get_store()
        wake_key = f"approval:{approval_id}"
        pid = owner_pid if owner_pid is not None else os.getpid()
        if approved:
            woken = store.deliver_event(wake_key)
            # Ensure transitioned to running
            for run in woken:
                try:
                    store.transition(run.id, WorkState.RUNNING.value, reason="approval_granted")
                except Exception:
                    pass
            return woken
        else:
            # Denied: cancel or fail waiting runs
            runs = store.list(state="waiting_for_user", wake_key=wake_key)
            cancelled = []
            for run in runs:
                cancelled.append(
                    store.transition(run.id, WorkState.CANCELLED.value, reason="approval_denied")
                )
            return cancelled

    def recover_orphaned_runs(
        self,
        is_alive: Callable[[int], bool] | None = None,
    ) -> list[str]:
        """Audit running/active runs whose owner pid has died and mark them INTERRUPTED/RECOVERABLE."""
        store = self._get_store()
        probe = is_alive if is_alive is not None else _default_pid_alive
        orphaned = []
        active_runs = store.list(state="active") + store.list(state="running")
        for run in active_runs:
            if run.owner_pid and not probe(run.owner_pid):
                logger.warning(
                    "Run %s owned by dead PID %d; moving to INTERRUPTED",
                    run.id,
                    run.owner_pid,
                )
                try:
                    store.transition(
                        run.id,
                        WorkState.INTERRUPTED.value,
                        reason="owner_pid_terminated",
                    )
                    orphaned.append(run.id)
                except Exception as exc:
                    logger.error("Failed to interrupt orphaned run %s: %s", run.id, exc)
        return orphaned


def _default_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
