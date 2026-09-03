"""Stable contracts between Jaeger and independently owned agent runtimes.

Delegate output is evidence, never authority.  In particular, a runtime may
return memory *candidates*, but only Jaeger's memory admission path may promote
them into canonical memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

Sensitivity = Literal["public", "personal", "sensitive", "private", "secret"]
ResultStatus = Literal["completed", "blocked", "failed", "cancelled"]
SENSITIVITIES = frozenset({"public", "personal", "sensitive", "private", "secret"})


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    available: bool
    detail: str = ""
    capabilities: frozenset[str] = frozenset()
    local: bool = True


@dataclass(frozen=True, slots=True)
class DelegateRequest:
    task_id: str
    prompt: str
    parent_task_id: str | None = None
    workspace: Path | None = None
    required_capabilities: frozenset[str] = frozenset()
    sensitivity: Sensitivity = "personal"
    allowed_tools: frozenset[str] = frozenset()
    timeout_seconds: int = 3600
    idempotency_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("delegate task_id must not be empty")
        if not self.prompt.strip():
            raise ValueError("delegate prompt must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("delegate timeout_seconds must be positive")
        if not self.idempotency_key.strip():
            raise ValueError("delegate idempotency_key must not be empty")
        if self.sensitivity not in SENSITIVITIES:
            raise ValueError(f"unknown delegate sensitivity: {self.sensitivity}")
        if self.workspace is not None and not self.workspace.is_absolute():
            raise ValueError("delegate workspace must be an absolute path")


@dataclass(frozen=True, slots=True)
class DelegateHandle:
    task_id: str
    runtime_id: str
    worker_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class DelegateArtifact:
    kind: str
    uri: str
    digest: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DelegateEvent:
    sequence: int
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DelegateResult:
    status: ResultStatus
    summary: str
    artifacts: tuple[DelegateArtifact, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    worker_session_id: str | None = None
    memory_candidates: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DelegateRuntime(Protocol):
    """Lifecycle port implemented by Claude, Codex, Hermes, OpenClaw, etc."""

    runtime_id: str

    async def probe(self) -> RuntimeStatus: ...

    async def start(self, request: DelegateRequest) -> DelegateHandle: ...

    def stream(self, handle: DelegateHandle) -> AsyncIterator[DelegateEvent]: ...

    async def result(self, handle: DelegateHandle) -> DelegateResult: ...

    async def cancel(self, handle: DelegateHandle) -> None: ...

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle: ...
