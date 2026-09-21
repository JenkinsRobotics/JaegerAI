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
    EXECUTIVE_DECISION = "executive.decision"
    PLAN_GENERATED = "plan.generated"
    TOOL_PROPOSED = "tool.proposed"
    AUTHORITY_DECISION = "authority.decision"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    VERIFICATION_COMPLETED = "verification.completed"
    LEARNING_UPDATED = "learning.updated"
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
    parent_event_id: str = ""

    def __post_init__(self) -> None:
        if not self.event_id:
            object.__setattr__(self, "event_id", f"evt-{uuid.uuid4().hex[:12]}")
        if not self.timestamp:
            object.__setattr__(self, "timestamp", time.time())
        if self.parent_event_id and "parent_event_id" not in self.provenance:
            # Ensure provenance contains parent_event_id for backward compatibility
            prov = dict(self.provenance)
            prov["parent_event_id"] = self.parent_event_id
            object.__setattr__(self, "provenance", prov)

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
            "parent_event_id": self.parent_event_id,
        }

    @property
    def metadata(self) -> dict[str, Any]:
        return self.provenance

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JaegerEvent:
        prov = dict(data.get("provenance") or {})
        parent_id = str(data.get("parent_event_id") or prov.get("parent_event_id") or "")
        return cls(
            event_id=str(data.get("event_id") or f"evt-{uuid.uuid4().hex[:12]}"),
            event_type=str(data.get("event_type") or EventType.SYSTEM_OBSERVATION.value),
            actor=str(data.get("actor") or "system:runtime"),
            source=str(data.get("source") or "runtime"),
            timestamp=float(data.get("timestamp") or time.time()),
            session_id=str(data.get("session_id") or "dispatcher"),
            payload=dict(data.get("payload") or {}),
            provenance=prov,
            salience=float(data.get("salience") or 0.5),
            idempotency_key=str(data["idempotency_key"]) if data.get("idempotency_key") else None,
            parent_event_id=parent_id,
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
        parent_event_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> JaegerEvent:
        if request_id:
            digest = hashlib.sha256(f"{session_id}:{request_id}".encode()).hexdigest()[:16]
            idemp_key = f"human-msg-req-{digest}"
        else:
            digest = hashlib.sha256(f"{session_id}:{text}".encode()).hexdigest()[:16]
            idemp_key = f"human-msg-{digest}"
        payload: dict[str, Any] = {"text": text, "request_id": request_id}
        if metadata:
            for k in ("role", "execution_mode", "actionable", "specialist", "agent_id"):
                if k in metadata:
                    payload[k] = metadata[k]
        return cls(
            event_id=f"msg-{uuid.uuid4().hex[:10]}",
            event_type=EventType.HUMAN_MESSAGE.value,
            actor=actor,
            source=source,
            timestamp=time.time(),
            session_id=session_id,
            payload=payload,
            salience=salience,
            idempotency_key=idemp_key,
            parent_event_id=parent_event_id,
            provenance=metadata or {},
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
        parent_event_id: str = "",
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
            parent_event_id=parent_event_id,
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
        parent_event_id: str = "",
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
            parent_event_id=parent_event_id,
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
        parent_event_id: str = "",
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
            parent_event_id=parent_event_id,
        )

    @classmethod
    def executive_decision(
        cls,
        strategy: str,
        reason: str,
        *,
        parent_event_id: str,
        session_id: str = "dispatcher",
        salience: float = 0.5,
    ) -> JaegerEvent:
        return cls(
            event_id=f"dec-{uuid.uuid4().hex[:10]}",
            event_type=EventType.EXECUTIVE_DECISION.value,
            actor="agent:executive",
            source="executive_strategy_selector",
            timestamp=time.time(),
            session_id=session_id,
            payload={"strategy": strategy, "reason": reason},
            salience=salience,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def plan_generated(
        cls,
        plan_summary: str,
        steps: list[str],
        *,
        parent_event_id: str,
        session_id: str = "dispatcher",
        salience: float = 0.5,
    ) -> JaegerEvent:
        return cls(
            event_id=f"pln-{uuid.uuid4().hex[:10]}",
            event_type=EventType.PLAN_GENERATED.value,
            actor="agent:planner",
            source="deliberate_search",
            timestamp=time.time(),
            session_id=session_id,
            payload={"plan_summary": plan_summary, "steps": steps},
            salience=salience,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def tool_proposed(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        parent_event_id: str,
        session_id: str = "dispatcher",
        salience: float = 0.4,
    ) -> JaegerEvent:
        return cls(
            event_id=f"tpr-{uuid.uuid4().hex[:10]}",
            event_type=EventType.TOOL_PROPOSED.value,
            actor="agent:cognition",
            source="cognition_router",
            timestamp=time.time(),
            session_id=session_id,
            payload={"tool": tool_name, "arguments": arguments},
            salience=salience,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def authority_decision(
        cls,
        tool_name: str,
        approved: bool,
        reason: str = "",
        *,
        parent_event_id: str,
        session_id: str = "dispatcher",
        salience: float = 0.5,
    ) -> JaegerEvent:
        return cls(
            event_id=f"ath-{uuid.uuid4().hex[:10]}",
            event_type=EventType.AUTHORITY_DECISION.value,
            actor="system:authority",
            source="authority_layer",
            timestamp=time.time(),
            session_id=session_id,
            payload={"tool": tool_name, "approved": approved, "reason": reason},
            salience=salience,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def verification_completed(
        cls,
        objective: str,
        status: str,
        evidence: str,
        verifier: str,
        *,
        parent_event_id: str,
        error: str | None = None,
        session_id: str = "dispatcher",
        salience: float = 0.6,
    ) -> JaegerEvent:
        return cls(
            event_id=f"vrf-{uuid.uuid4().hex[:10]}",
            event_type=EventType.VERIFICATION_COMPLETED.value,
            actor="system:verifier",
            source="verification_registry",
            timestamp=time.time(),
            session_id=session_id,
            payload={
                "objective": objective,
                "status": status,
                "evidence": evidence,
                "verifier": verifier,
                "error": error,
            },
            salience=salience,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def learning_updated(
        cls,
        learning_type: str,
        summary: str,
        *,
        parent_event_id: str,
        session_id: str = "dispatcher",
        salience: float = 0.4,
    ) -> JaegerEvent:
        return cls(
            event_id=f"lrn-{uuid.uuid4().hex[:10]}",
            event_type=EventType.LEARNING_UPDATED.value,
            actor="system:learning",
            source="learning_pipeline",
            timestamp=time.time(),
            session_id=session_id,
            payload={"learning_type": learning_type, "summary": summary},
            salience=salience,
            parent_event_id=parent_event_id,
        )

    @classmethod
    def agent_response(
        cls,
        text: str,
        *,
        parent_event_id: str,
        session_id: str = "dispatcher",
        actor: str = "agent:jaeger",
        source: str = "cognition",
        salience: float = 0.5,
    ) -> JaegerEvent:
        return cls(
            event_id=f"rsp-{uuid.uuid4().hex[:10]}",
            event_type=EventType.AGENT_RESPONSE.value,
            actor=actor,
            source=source,
            timestamp=time.time(),
            session_id=session_id,
            payload={"text": text},
            salience=salience,
            parent_event_id=parent_event_id,
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
