"""Multi-Agent Domain Models (Workstream 12).

Defines:
- Agent identities & types (Persistent Sovereign vs Subordinate Worker)
- Trust relationships
- Scoped capability grants
- Inter-agent messages and delegation tasks
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any
import uuid


class AgentType(str, Enum):
    PERSISTENT_SOVEREIGN = "persistent_sovereign"
    SUBORDINATE_WORKER = "subordinate_worker"


class TrustLevel(str, Enum):
    SOVEREIGN = "sovereign"
    TRUSTED_PEER = "trusted_peer"
    SUBORDINATE = "subordinate"
    UNTRUSTED_EXTERNAL = "untrusted_external"


class DelegationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AgentMessage:
    """Structured message communicated between agents."""
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    sender_id: str = "agent:jaeger"
    recipient_id: str = "agent:worker"
    topic: str = "general"
    payload: dict[str, Any] = field(default_factory=dict)
    sent_at: float = field(default_factory=time.time)


@dataclass
class DelegationTask:
    """A task delegated from a parent sovereign agent to a subordinate worker or peer."""
    delegation_id: str = field(default_factory=lambda: f"del_{uuid.uuid4().hex[:12]}")
    parent_entity_id: str = "agent:jaeger"
    assigned_to_entity_id: str = ""
    goal: str = ""
    capability_grants: tuple[str, ...] = ()
    status: DelegationStatus = DelegationStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
