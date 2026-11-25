"""Pregel superstep graph (LangGraph Send/interrupt/Command), Agno RunAuthorization & attempt-fenced queue,
and AG2 ScopedVariables (LOCAL / COPIED / SHARED).
"""

from __future__ import annotations

import contextlib
import copy
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterator, Mapping, Sequence


# ---------------------------------------------------------------------------
# LangGraph: Send() map-reduce + interrupt() / Command(resume=...) + PregelGraph
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Send:
    """Dynamic fan-out dispatch to a target node with branch-specific input."""

    node: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class Command:
    """Resume or direct a Pregel graph run (LangGraph Command pattern)."""

    resume: Any = None
    update: Mapping[str, Any] = field(default_factory=dict)
    goto: str | None = None


class GraphInterrupt(Exception):
    """Raised internally by ``interrupt()`` to pause a graph node cleanly."""

    def __init__(self, value: Any) -> None:
        super().__init__(str(value))
        self.value = value


_UNSET = object()
_resume_value_var: ContextVar[Any] = ContextVar("jaeger_pregel_resume", default=_UNSET)


def interrupt(value: Any) -> Any:
    """Pause the current Pregel node and surface ``value`` to the caller.

    When resumed with ``Command(resume=answer)``, returns ``answer`` instead of raising.
    """
    current = _resume_value_var.get()
    if current is not _UNSET:
        _resume_value_var.set(_UNSET)
        return current
    raise GraphInterrupt(value)


@dataclass
class PregelRunResult:
    run_id: str
    status: str  # "completed" | "interrupted"
    state: dict[str, Any]
    interrupt_value: Any = None
    interrupted_node: str | None = None
    steps_executed: int = 0


class PregelGraph:
    """Superstep-based DAG/graph runner supporting Send() map-reduce & interrupt()/Command(resume=...)."""

    def __init__(self, *, reducers: Mapping[str, Callable[[Any, Any], Any]] | None = None) -> None:
        self._nodes: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._edges: dict[str, list[str]] = {}
        self._conditional_edges: dict[str, Callable[[dict[str, Any]], str | Sequence[str | Send] | None]] = {}
        self._reducers: dict[str, Callable[[Any, Any], Any]] = dict(reducers or {})
        self._entry: str | None = None
        self._suspended: dict[str, tuple[str, dict[str, Any], int]] = {}

    def add_node(self, name: str, fn: Callable[[dict[str, Any]], Any]) -> "PregelGraph":
        self._nodes[name] = fn
        if self._entry is None:
            self._entry = name
        return self

    def set_entry(self, name: str) -> "PregelGraph":
        if name not in self._nodes:
            raise KeyError(f"Unknown node: {name!r}")
        self._entry = name
        return self

    def add_edge(self, src: str, dst: str) -> "PregelGraph":
        self._edges.setdefault(src, []).append(dst)
        return self

    def add_conditional_edges(
        self,
        src: str,
        router: Callable[[dict[str, Any]], str | Sequence[str | Send] | None],
    ) -> "PregelGraph":
        self._conditional_edges[src] = router
        return self

    def _merge(self, state: dict[str, Any], update: Mapping[str, Any]) -> None:
        for k, v in update.items():
            if k in self._reducers and k in state:
                state[k] = self._reducers[k](state[k], v)
            else:
                state[k] = v

    def invoke(
        self,
        initial_state: Mapping[str, Any] | Command,
        *,
        run_id: str | None = None,
        max_steps: int = 100,
    ) -> PregelRunResult:
        rid = run_id or f"pg_{uuid.uuid4().hex[:10]}"
        if isinstance(initial_state, Command):
            if rid not in self._suspended:
                raise KeyError(f"No interrupted run found for run_id={rid!r}")
            start_node, state, steps = self._suspended.pop(rid)
            if initial_state.update:
                self._merge(state, initial_state.update)
            queue: list[tuple[str, Mapping[str, Any] | None]] = [
                (initial_state.goto or start_node, None)
            ]
            resume_token = _resume_value_var.set(initial_state.resume)
        else:
            if self._entry is None:
                raise ValueError("PregelGraph has no nodes")
            state = dict(initial_state)
            steps = 0
            queue = [(self._entry, None)]
            resume_token = _resume_value_var.set(_UNSET)

        try:
            while queue and steps < max_steps:
                node_name, override_payload = queue.pop(0)
                if node_name not in self._nodes:
                    continue
                fn = self._nodes[node_name]
                node_input = dict(override_payload) if override_payload is not None else dict(state)
                try:
                    out = fn(node_input)
                except GraphInterrupt as intr:
                    self._suspended[rid] = (node_name, dict(state), steps)
                    return PregelRunResult(
                        run_id=rid,
                        status="interrupted",
                        state=dict(state),
                        interrupt_value=intr.value,
                        interrupted_node=node_name,
                        steps_executed=steps,
                    )

                steps += 1
                if isinstance(out, Mapping):
                    self._merge(state, out)

                if node_name in self._conditional_edges:
                    routed = self._conditional_edges[node_name](state)
                    if isinstance(routed, str):
                        queue.append((routed, None))
                    elif isinstance(routed, Send):
                        queue.append((routed.node, routed.payload))
                    elif isinstance(routed, Sequence):
                        for item in routed:
                            if isinstance(item, Send):
                                queue.append((item.node, item.payload))
                            elif isinstance(item, str):
                                queue.append((item, None))
                for nxt in self._edges.get(node_name, ()):
                    if (nxt, None) not in queue:
                        queue.append((nxt, None))

            return PregelRunResult(
                run_id=rid,
                status="completed",
                state=dict(state),
                steps_executed=steps,
            )
        finally:
            _resume_value_var.reset(resume_token)


# ---------------------------------------------------------------------------
# Agno: ContextVar RunAuthorization & attempt-fenced job queue
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RunAuthorization:
    """Immutable run-scoped authorization identity carried via ContextVar."""

    actor: str
    run_id: str
    scopes: frozenset[str] = frozenset()
    attempt: int = 1

    def has_scope(self, scope: str) -> bool:
        return "*" in self.scopes or scope in self.scopes


_auth_var: ContextVar[RunAuthorization | None] = ContextVar("jaeger_run_authorization", default=None)


@contextlib.contextmanager
def bind_authorization(auth: RunAuthorization) -> Iterator[RunAuthorization]:
    token = _auth_var.set(auth)
    try:
        yield auth
    finally:
        _auth_var.reset(token)


def current_authorization() -> RunAuthorization | None:
    return _auth_var.get()


class StaleAttemptError(RuntimeError):
    """Raised when a superseded worker attempts to commit a job outcome."""


@dataclass
class FencedJob:
    job_id: str
    payload: dict[str, Any]
    status: str = "queued"  # queued | running | completed | failed
    attempt: int = 0
    result: Any = None
    error: str = ""
    updated_at: float = field(default_factory=time.time)


class AttemptFencedQueue:
    """Job queue with monotonic attempt fencing (Agno zombie-worker protection)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, FencedJob] = {}
        self._order: list[str] = []

    def enqueue(self, payload: Mapping[str, Any], *, job_id: str | None = None) -> FencedJob:
        jid = job_id or f"job_{uuid.uuid4().hex[:10]}"
        job = FencedJob(job_id=jid, payload=dict(payload))
        with self._lock:
            self._jobs[jid] = job
            self._order.append(jid)
        return job

    def claim(self, job_id: str | None = None) -> tuple[FencedJob, int] | None:
        """Claim a queued (or re-claimed) job, incrementing its monotonic attempt fence."""
        with self._lock:
            target: FencedJob | None = None
            if job_id is not None:
                cand = self._jobs.get(job_id)
                if cand is not None and cand.status in ("queued", "running"):
                    target = cand
            else:
                for jid in self._order:
                    cand = self._jobs[jid]
                    if cand.status == "queued":
                        target = cand
                        break
            if target is None:
                return None
            target.attempt += 1
            target.status = "running"
            target.updated_at = time.time()
            return target, target.attempt

    def complete(self, job_id: str, attempt: int, result: Any) -> FencedJob:
        with self._lock:
            job = self._jobs[job_id]
            if attempt != job.attempt:
                raise StaleAttemptError(
                    f"stale attempt {attempt} for {job_id!r} (current attempt={job.attempt})"
                )
            job.status = "completed"
            job.result = result
            job.updated_at = time.time()
            return job

    def fail(self, job_id: str, attempt: int, error: str) -> FencedJob:
        with self._lock:
            job = self._jobs[job_id]
            if attempt != job.attempt:
                raise StaleAttemptError(
                    f"stale attempt {attempt} for {job_id!r} (current attempt={job.attempt})"
                )
            job.status = "failed"
            job.error = error
            job.updated_at = time.time()
            return job

    def get(self, job_id: str) -> FencedJob | None:
        with self._lock:
            return self._jobs.get(job_id)


# ---------------------------------------------------------------------------
# AG2: ScopedVariables (LOCAL / COPIED / SHARED)
# ---------------------------------------------------------------------------

class VarScope(str, Enum):
    LOCAL = "local"
    COPIED = "copied"
    SHARED = "shared"


class ScopedVariables:
    """Multi-agent context variable container with explicit LOCAL/COPIED/SHARED semantics (AG2)."""

    def __init__(
        self,
        *,
        local: Mapping[str, Any] | None = None,
        copied: Mapping[str, Any] | None = None,
        shared: dict[str, Any] | None = None,
    ) -> None:
        self._local: dict[str, Any] = dict(local or {})
        self._copied: dict[str, Any] = dict(copied or {})
        self._shared: dict[str, Any] = shared if shared is not None else {}

    def set(self, key: str, value: Any, *, scope: VarScope = VarScope.LOCAL) -> None:
        if scope == VarScope.LOCAL:
            self._local[key] = value
        elif scope == VarScope.COPIED:
            self._copied[key] = value
        elif scope == VarScope.SHARED:
            self._shared[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._local:
            return self._local[key]
        if key in self._copied:
            return self._copied[key]
        if key in self._shared:
            return self._shared[key]
        return default

    def fork_for_child(self) -> "ScopedVariables":
        """Create a child variable view: omit LOCAL, deep-copy COPIED, share SHARED by reference."""
        return ScopedVariables(
            local={},
            copied=copy.deepcopy(self._copied),
            shared=self._shared,
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            "local": dict(self._local),
            "copied": copy.deepcopy(self._copied),
            "shared": copy.deepcopy(self._shared),
        }


__all__ = [
    "AttemptFencedQueue",
    "Command",
    "FencedJob",
    "GraphInterrupt",
    "PregelGraph",
    "PregelRunResult",
    "RunAuthorization",
    "ScopedVariables",
    "Send",
    "StaleAttemptError",
    "VarScope",
    "bind_authorization",
    "current_authorization",
    "interrupt",
]
