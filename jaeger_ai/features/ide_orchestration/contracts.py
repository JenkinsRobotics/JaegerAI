"""Contracts and state definitions for IDE Worker Orchestration."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskState = Literal[
    "queued",
    "submitted",
    "running",
    "completed",
    "failed",
    "blocked",
    "quota",
    "auth",
    "approval",
    "unknown",
]

TASK_STATES: frozenset[str] = frozenset(
    {
        "queued",
        "submitted",
        "running",
        "completed",
        "failed",
        "blocked",
        "quota",
        "auth",
        "approval",
        "unknown",
    }
)

TERMINAL_STATES: frozenset[str] = frozenset(
    {
        "completed",
        "failed",
        "blocked",
        "quota",
        "auth",
        "unknown",
    }
)


@dataclass(frozen=True, slots=True)
class TaskBudget:
    max_seconds: float = 300.0
    max_turns: int = 1
    max_cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_seconds) or self.max_seconds <= 0:
            raise ValueError("max_seconds must be positive")
        if self.max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if not math.isfinite(self.max_cost_usd) or self.max_cost_usd < 0:
            raise ValueError("max_cost_usd cannot be negative")


@dataclass(frozen=True, slots=True)
class ParentTask:
    task_id: str
    goal: str
    assigned_worker: str  # "codex", "claude", "gemini"
    idempotency_key: str
    workspace: Path | None = None
    read_only: bool = True
    budget: TaskBudget = field(default_factory=TaskBudget)
    metadata: dict[str, Any] = field(default_factory=dict)
    required_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id must not be empty")
        if not self.goal.strip():
            raise ValueError("goal must not be empty")
        if not self.assigned_worker.strip():
            raise ValueError("assigned_worker must not be empty")
        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        if self.workspace is not None and not self.workspace.is_absolute():
            raise ValueError("workspace must be an absolute path")


@dataclass(frozen=True, slots=True)
class WorkerProgress:
    task_id: str
    state: TaskState
    sequence: int
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verified: bool
    reason: str
    checked_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    task_id: str
    worker_id: str
    state: TaskState
    output: str
    verification: VerificationResult
    budget_used_seconds: float
    evidence: dict[str, Any] = field(default_factory=dict)
