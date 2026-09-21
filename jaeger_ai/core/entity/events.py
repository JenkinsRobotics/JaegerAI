"""Canonical Event Contract for Jaeger Persistent Entity (Pinocchio Architecture).

All occurrences in the entity lifecycle — human interaction, tool invocations,
environmental observations, heartbeats, background tasks, and memory consolidation —
are represented as normalized JaegerEvent records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any
import uuid


class EventType(str, Enum):
    HUMAN_MESSAGE = "human.message"
    SYSTEM_HEARTBEAT = "system.heartbeat"
    SYSTEM_OBSERVATION = "system.observation"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    GOAL_CREATED = "goal.created"
    GOAL_COMPLETED = "goal.completed"
    COMMITMENT_CREATED = "commitment.created"
    COMMITMENT_UPDATED = "commitment.updated"
    AGENT_ACTION = "agent.action"
    AGENT_RESPONSE = "agent.response"
    MEMORY_CONSOLIDATED = "memory.consolidated"
    BACKGROUND_COMPLETED = "background.completed"
    PERCEPTION_SENSED = "perception.sensed"
    SKILL_CANDIDATE = "skill.candidate"
    SKILL_PROMOTED = "skill.promoted"


@dataclass(frozen=True)
class JaegerEvent:
    """A single normalized event in the persistent entity log."""

    event_id: str
    event_type: str
    actor: str
    source: str
    timestamp: float
    session_id: str = "dispatcher"
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    salience: float = 0.5
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            object.__setattr__(self, "event_id", f"evt-{uuid.uuid4().hex[:12]}")
        if not self.timestamp:
            object.__setattr__(self, "timestamp", time.time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": str(self.event_type),
            "actor": self.actor,
            "source": self.source,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "payload": self.payload,
            "provenance": self.provenance,
            "salience": self.salience,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JaegerEvent:
        return cls(
            event_id=str(data.get("event_id") or f"evt-{uuid.uuid4().hex[:12]}"),
            event_type=str(data.get("event_type") or EventType.SYSTEM_OBSERVATION.value),
            actor=str(data.get("actor") or "system:runtime"),
            source=str(data.get("source") or "runtime"),
            timestamp=float(data.get("timestamp") or time.time()),
            session_id=str(data.get("session_id") or "dispatcher"),
            payload=dict(data.get("payload") or {}),
            provenance=dict(data.get("provenance") or {}),
            salience=float(data.get("salience") or 0.5),
            idempotency_key=str(data["idempotency_key"]) if data.get("idempotency_key") else None,
        )

    # ── Factory Constructors ──────────────────────────────────────────

    @classmethod
    def human_message(
        cls,
        text: str,
        *,
        actor: str = "human:operator",
        source: str = "chat",
        session_id: str = "dispatcher",
        salience: float = 1.0,
        request_id: str | None = None,
    ) -> JaegerEvent:
        digest = hashlib.sha256(f"{session_id}:{text}".encode()).hexdigest()[:16]
        return cls(
            event_id=f"msg-{uuid.uuid4().hex[:10]}",
            event_type=EventType.HUMAN_MESSAGE.value,
            actor=actor,
            source=source,
            timestamp=time.time(),
            session_id=session_id,
            payload={"text": text, "request_id": request_id},
            salience=salience,
            idempotency_key=f"human-msg-{digest}",
        )

    @classmethod
    def heartbeat(
        cls,
        *,
        source: str = "runtime.heartbeat",
        session_id: str = "system",
        payload: dict[str, Any] | None = None,
        salience: float = 0.2,
    ) -> JaegerEvent:
        return cls(
            event_id=f"hbt-{uuid.uuid4().hex[:10]}",
            event_type=EventType.SYSTEM_HEARTBEAT.value,
            actor="system:heartbeat",
            source=source,
            timestamp=time.time(),
            session_id=session_id,
            payload=payload or {},
            salience=salience,
        )

    @classmethod
    def tool_started(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str,
        session_id: str = "dispatcher",
        actor: str = "agent:jaeger",
    ) -> JaegerEvent:
        return cls(
            event_id=f"tls-{uuid.uuid4().hex[:10]}",
            event_type=EventType.TOOL_STARTED.value,
            actor=actor,
            source="runtime.tool_executor",
            timestamp=time.time(),
            session_id=session_id,
            payload={"tool": tool_name, "arguments": arguments, "call_id": call_id},
            salience=0.3,
            idempotency_key=f"tool-start-{call_id}",
        )

    @classmethod
    def tool_completed(
        cls,
        tool_name: str,
        result: Any,
        *,
        call_id: str,
        duration_s: float,
        session_id: str = "dispatcher",
        actor: str = "tool:" + "system",
    ) -> JaegerEvent:
        return cls(
            event_id=f"tlc-{uuid.uuid4().hex[:10]}",
            event_type=EventType.TOOL_COMPLETED.value,
            actor=f"tool:{tool_name}",
            source="runtime.tool_executor",
            timestamp=time.time(),
            session_id=session_id,
            payload={"tool": tool_name, "result": result, "call_id": call_id, "duration_s": duration_s},
            salience=0.6,
            idempotency_key=f"tool-done-{call_id}",
        )

    @classmethod
    def tool_failed(
        cls,
        tool_name: str,
        error: str,
        *,
        call_id: str,
        duration_s: float,
        session_id: str = "dispatcher",
    ) -> JaegerEvent:
        return cls(
            event_id=f"tlf-{uuid.uuid4().hex[:10]}",
            event_type=EventType.TOOL_FAILED.value,
            actor=f"tool:{tool_name}",
            source="runtime.tool_executor",
            timestamp=time.time(),
            session_id=session_id,
            payload={"tool": tool_name, "error": error, "call_id": call_id, "duration_s": duration_s},
            salience=0.8,
            idempotency_key=f"tool-fail-{call_id}",
        )

    @classmethod
    def perception_sensed(
        cls,
        sensor: str,
        signals: dict[str, Any],
        *,
        salience: float = 0.2,
        session_id: str = "system",
    ) -> JaegerEvent:
        return cls(
            event_id=f"sen-{uuid.uuid4().hex[:10]}",
            event_type=EventType.PERCEPTION_SENSED.value,
            actor=f"sensor:{sensor}",
            source=f"sensor.{sensor}",
            timestamp=time.time(),
            session_id=session_id,
            payload=signals,
            salience=salience,
        )
