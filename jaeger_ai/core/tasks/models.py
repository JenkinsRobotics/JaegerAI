"""Durable Task and Scheduling Domain Models (Workstream 15).

Unifies background work, scheduled jobs, automations, long-running tasks,
monitoring, and delegated work into a single durable lifecycle.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import time
from typing import Any
import uuid


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_VERIFIED = "completed_verified"
    NEEDS_OWNER = "needs_owner"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class TaskKind(str, Enum):
    BACKGROUND_WORK = "background_work"
    SCHEDULED_JOB = "scheduled_job"
    AUTOMATION = "automation"
    LONG_RUNNING = "long_running"
    MONITORING = "monitoring"
    DELEGATED = "delegated"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_seconds: float = 5.0
    current_retries: int = 0

    def can_retry(self) -> bool:
        return self.current_retries < self.max_retries


@dataclass
class NotificationPolicy:
    notify_on_completion: bool = True
    recipient_session_id: str | None = None
    channels: list[str] = field(default_factory=lambda: ["sse", "inbox"])


@dataclass
class TaskRunRecord:
    run_id: str
    started_at: float
    completed_at: float | None = None
    status: str = "running"
    error: str | None = None


@dataclass
class DurableTask:
    """Canonical durable unit of background work surviving client disconnects and restarts."""
    task_id: str
    owning_agent: str
    goal: str
    kind: TaskKind = TaskKind.BACKGROUND_WORK
    state: TaskState = TaskState.QUEUED
    payload: dict[str, Any] = field(default_factory=dict)
    run_history: list[TaskRunRecord] = field(default_factory=list)
    next_execution: float | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    cancellation: str | None = None
    result: Any = None
    error: str | None = None
    notification_policy: NotificationPolicy = field(default_factory=NotificationPolicy)
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_terminal(self) -> bool:
        return self.state in (
            TaskState.COMPLETED,
            TaskState.COMPLETED_VERIFIED,
            TaskState.NEEDS_OWNER,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "owning_agent": self.owning_agent,
            "goal": self.goal,
            "kind": self.kind.value,
            "state": self.state.value,
            "payload": self.payload,
            "run_history": [asdict(r) for r in self.run_history],
            "next_execution": self.next_execution,
            "retry_policy": asdict(self.retry_policy),
            "cancellation": self.cancellation,
            "result": self.result,
            "error": self.error,
            "notification_policy": asdict(self.notification_policy),
            "provenance": self.provenance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DurableTask:
        runs = [
            TaskRunRecord(
                run_id=r["run_id"],
                started_at=r["started_at"],
                completed_at=r.get("completed_at"),
                status=r.get("status", "running"),
                error=r.get("error"),
            )
            for r in (data.get("run_history") or [])
        ]
        rp_data = data.get("retry_policy") or {}
        np_data = data.get("notification_policy") or {}

        return cls(
            task_id=data["task_id"],
            owning_agent=data["owning_agent"],
            goal=data["goal"],
            kind=TaskKind(data.get("kind", TaskKind.BACKGROUND_WORK.value)),
            state=TaskState(data.get("state", TaskState.QUEUED.value)),
            payload=dict(data.get("payload") or {}),
            run_history=runs,
            next_execution=data.get("next_execution"),
            retry_policy=RetryPolicy(
                max_retries=rp_data.get("max_retries", 3),
                backoff_seconds=rp_data.get("backoff_seconds", 5.0),
                current_retries=rp_data.get("current_retries", 0),
            ),
            cancellation=data.get("cancellation"),
            result=data.get("result"),
            error=data.get("error"),
            notification_policy=NotificationPolicy(
                notify_on_completion=np_data.get("notify_on_completion", True),
                recipient_session_id=np_data.get("recipient_session_id"),
                channels=list(np_data.get("channels") or ["sse", "inbox"]),
            ),
            provenance=dict(data.get("provenance") or {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
        )


@dataclass
class Goal:
    """What the owner asked for. It lives on the durable task, not in its own store."""
    goal_id: str
    owner: str
    objective: str
    session_id: str
    privacy: str = "private"
    interruption: str = "continue"
    invented: bool = False
    created_at: float = field(default_factory=time.time)

    @classmethod
    def from_owner(cls, *, owner: str, objective: str, session_id: str, **kwargs: Any) -> Goal:
        return cls(goal_id=f"goal_{uuid.uuid4().hex[:12]}", owner=owner, objective=objective,
                   session_id=session_id, **kwargs)


@dataclass
class TaskCard:
    """The fields a turn-owned task carries in ``DurableTask.payload['turn_card']``.

    The card never sets task state. ``GatewayTaskOwner`` is the only writer, and
    only through ``authoritative_transition``.
    """
    task_id: str
    goal_id: str
    goal: str
    owner: str
    session_id: str
    request_id: str = ""
    strategy: str = ""
    privacy: str = "private"
    allowed_capabilities: tuple[str, ...] = ()
    prohibited_capabilities: tuple[str, ...] = ("minecraft", "mc_status", "desktop_control")
    success_criteria: str = ""
    verification_criteria: str = "real evidence, not a bare success flag"
    interruption: str = "continue"

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_capabilities"] = list(self.allowed_capabilities)
        data["prohibited_capabilities"] = list(self.prohibited_capabilities)
        return data

    @classmethod
    def open(cls, goal: Goal, *, strategy: str = "", request_id: str = "", task_id: str = "",
             allowed: tuple[str, ...] = ()) -> TaskCard:
        return cls(
            task_id=task_id or f"task_{uuid.uuid4().hex[:12]}",
            goal_id=goal.goal_id,
            goal=goal.objective,
            owner=goal.owner,
            session_id=goal.session_id,
            request_id=request_id,
            strategy=strategy,
            privacy=goal.privacy,
            allowed_capabilities=allowed,
            interruption=goal.interruption,
            success_criteria=goal.objective,
        )


@dataclass(frozen=True)
class Receipt:
    """What came back to the conversation for one task: facts, not a status flag."""
    receipt_id: str
    task_id: str
    session_id: str
    goal: str
    state: str
    verification: str
    evidence: Any
    strategy: str = ""
    models: tuple[str, ...] = ()
    entity_id: str = ""
    identity_name: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["models"] = list(self.models)
        return data
