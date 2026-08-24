"""Runs and checkpoints — the durable execution layer under a commitment.

A commitment says *what* the SI intends. A run is one *attempt* at it,
and it is the thing that dies: the process is killed, the laptop sleeps,
the provider 500s, the user quits the UI. Durable cognition means the
next process can pick the attempt up rather than starting the thought
over, and can tell the difference between "this never ran" and "this ran
and I lost the answer".

Three mechanisms carry that:

``checkpoints``
    Append-only cursors written *by the runtime*, not by the model.
    Resumption reads the highest sequence number and continues. A
    checkpoint holds progress, never provider state — which is what
    makes it legal to resume a Claude-checkpointed run on Gemini.

``owner_pid`` + ``heartbeat``
    A run claims a process. When that process is gone, the claim is
    stale and ``recover`` says so — deterministically, by asking the OS
    whether the pid is alive, never by asking a model whether the work
    "seems finished".

``wake_key``
    A run in ``waiting_for_event`` names the event it is waiting for.
    ``deliver_event`` wakes exactly the runs holding that key. Waiting
    costs no process: the run is a row, not a blocked thread.

Recovery deliberately lands an orphaned run in ``blocked``, not
``failed``. The runtime knows the owner vanished; it does not know
whether the work succeeded first. Claiming either would be a guess, and
guesses about completed side effects are what the effect ledger
(``jaeger_agent.cognition.effects``) exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable
import os
import uuid

from jaeger_agent.cognition.lifecycle import (
    RESUMABLE,
    STATES,
    LifecycleError,
    check_transition,
    now as _now,
)


class RunError(LifecycleError):
    """Illegal transition, missing run, or resume of a run that is running."""


@dataclass(slots=True)
class Run:
    id: str
    commitment_id: str
    state: str
    attempt: int = 1
    owner_pid: int | None = None
    heartbeat_at: str | None = None
    wake_key: str | None = None
    provider: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class Checkpoint:
    run_id: str
    seq: int
    cursor: dict[str, Any]
    created_at: str


def pid_is_alive(pid: int) -> bool:
    """Default liveness probe for ``recover``. Signal 0 tests existence."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


@runtime_checkable
class RunStore(Protocol):
    """The durable runtime port. Swap SQLite for anything that keeps a row."""

    def create(self, commitment_id: str, *, provider: str | None = None,
               owner_pid: int | None = None,
               payload: dict[str, Any] | None = None) -> Run: ...

    def get(self, run_id: str) -> Run | None: ...

    def list(self, *, commitment_id: str | None = None,
             state: str | None = None) -> list[Run]: ...

    def transition(self, run_id: str, new_state: str, *,
                   reason: str | None = None,
                   wake_key: str | None = None) -> Run: ...

    def heartbeat(self, run_id: str, *, owner_pid: int | None = None) -> Run: ...

    def checkpoint(self, run_id: str, cursor: dict[str, Any]) -> Checkpoint: ...

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None: ...

    def resume(self, run_id: str, *, provider: str | None = None,
               owner_pid: int | None = None) -> tuple[Run, Checkpoint | None]: ...

    def recover(self, *,
                is_alive: Callable[[int], bool] = pid_is_alive) -> list[Run]: ...

    def deliver_event(self, wake_key: str) -> list[Run]: ...


# ── shared rules, so no adapter can quietly implement them differently ──


def check_wait(new_state: str, wake_key: str | None) -> None:
    """``waiting_for_event`` without a key is a run nothing can ever wake."""
    if new_state == "waiting_for_event" and not wake_key:
        raise RunError("waiting_for_event requires a wake_key")


def check_resumable(run: Run) -> None:
    if run.state not in RESUMABLE:
        raise RunError(
            f"cannot resume {run.id} from {run.state} "
            f"(resumable: {', '.join(sorted(RESUMABLE))})"
        )


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class InMemoryRunStore:
    """Reference implementation. The contract tests run against both this
    and the SQLite adapter, so a divergence is a test failure, not a
    production surprise."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._checkpoints: dict[str, list[Checkpoint]] = {}

    def create(self, commitment_id: str, *, provider: str | None = None,
               owner_pid: int | None = None,
               payload: dict[str, Any] | None = None) -> Run:
        now = _now()
        attempt = len(self.list(commitment_id=commitment_id)) + 1
        run = Run(
            id=new_id(),
            commitment_id=commitment_id,
            state="created",
            attempt=attempt,
            owner_pid=owner_pid,
            heartbeat_at=now if owner_pid is not None else None,
            provider=provider,
            payload=dict(payload or {}),
            created_at=now,
            updated_at=now,
        )
        self._runs[run.id] = run
        self._checkpoints[run.id] = []
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list(self, *, commitment_id: str | None = None,
             state: str | None = None) -> list[Run]:
        rows = list(self._runs.values())
        if commitment_id is not None:
            rows = [r for r in rows if r.commitment_id == commitment_id]
        if state is not None:
            rows = [r for r in rows if r.state == state]
        return sorted(rows, key=lambda r: (r.created_at, r.attempt))

    def _require(self, run_id: str) -> Run:
        run = self._runs.get(run_id)
        if run is None:
            raise RunError(f"no run {run_id!r}")
        return run

    def transition(self, run_id: str, new_state: str, *,
                   reason: str | None = None,
                   wake_key: str | None = None) -> Run:
        run = self._require(run_id)
        check_transition(run.id, run.state, new_state, error=RunError)
        check_wait(new_state, wake_key)
        run.state = new_state
        run.reason = reason
        run.wake_key = wake_key if new_state == "waiting_for_event" else None
        if new_state != "active":
            run.owner_pid = None  # the claim ends with the activity
        run.updated_at = _now()
        return run

    def heartbeat(self, run_id: str, *, owner_pid: int | None = None) -> Run:
        run = self._require(run_id)
        if owner_pid is not None:
            run.owner_pid = owner_pid
        run.heartbeat_at = _now()
        return run

    def checkpoint(self, run_id: str, cursor: dict[str, Any]) -> Checkpoint:
        run = self._require(run_id)
        seq = len(self._checkpoints[run.id]) + 1
        point = Checkpoint(run.id, seq, dict(cursor), _now())
        self._checkpoints[run.id].append(point)
        return point

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        self._require(run_id)
        points = self._checkpoints.get(run_id) or []
        return points[-1] if points else None

    def resume(self, run_id: str, *, provider: str | None = None,
               owner_pid: int | None = None) -> tuple[Run, Checkpoint | None]:
        run = self._require(run_id)
        check_resumable(run)
        run.state = "active"
        run.wake_key = None
        run.reason = None
        if provider is not None:
            run.provider = provider
        run.owner_pid = owner_pid
        run.heartbeat_at = _now()
        run.updated_at = run.heartbeat_at
        return run, self.latest_checkpoint(run_id)

    def recover(self, *,
                is_alive: Callable[[int], bool] = pid_is_alive) -> list[Run]:
        orphans = [
            r for r in self.list(state="active")
            if r.owner_pid is not None and not is_alive(r.owner_pid)
        ]
        return [
            self.transition(r.id, "blocked", reason="owner_lost")
            for r in orphans
        ]

    def deliver_event(self, wake_key: str) -> list[Run]:
        waiting = [
            r for r in self.list(state="waiting_for_event")
            if r.wake_key == wake_key
        ]
        woken = []
        for run in waiting:
            run.state = "active"
            run.wake_key = None
            run.reason = None
            run.updated_at = _now()
            woken.append(run)
        return woken


__all__ = [
    "RESUMABLE",
    "STATES",
    "Checkpoint",
    "InMemoryRunStore",
    "Run",
    "RunError",
    "RunStore",
    "check_resumable",
    "check_wait",
    "new_id",
    "pid_is_alive",
]
