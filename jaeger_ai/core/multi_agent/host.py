"""Multi-Agent Runtime Host (Workstream 12).

Enables running multiple sovereign and subordinate agents in a single host:
RuntimeHost
├── EntityRuntime(A) [Persistent Sovereign]
├── EntityRuntime(B) [Persistent Sovereign]
└── SubordinateWorker(C) [Scoped Subordinate]

Features:
- Complete private memory isolation (no state leakage between entities)
- Controlled shared memory collaboration blackboard
- Scoped delegation with capability grants
- Deterministic delegation cancellation
- Inter-agent message routing and inboxes
"""
from __future__ import annotations

from collections import defaultdict
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable

from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.runtime import EntityRuntime, EntityRuntimeMode
from .models import AgentMessage, AgentType, DelegationStatus, DelegationTask, TrustLevel

logger = logging.getLogger("jaeger.core.multi_agent.host")


class MultiAgentError(RuntimeError):
    pass


class RuntimeHost:
    """Central host coordinating multiple concurrent agent entities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entities: dict[str, EntityRuntime] = {}
        self._agent_types: dict[str, AgentType] = {}
        self._trust_matrix: dict[tuple[str, str], TrustLevel] = {}
        self._shared_memory: dict[str, Any] = {}
        self._inboxes: dict[str, list[AgentMessage]] = defaultdict(list)
        self._delegations: dict[str, DelegationTask] = {}

    # ── Entity Management ───────────────────────────────────────────────

    def register_entity(
        self,
        runtime: EntityRuntime,
        *,
        agent_type: AgentType = AgentType.PERSISTENT_SOVEREIGN,
    ) -> str:
        """Register an existing EntityRuntime into this host."""
        with self._lock:
            eid = runtime.identity.entity_id
            self._entities[eid] = runtime
            self._agent_types[eid] = agent_type
            logger.info("Registered entity %s (%s) as %s", eid, runtime.identity.display_name, agent_type.value)
            return eid

    def create_persistent_entity(
        self,
        display_name: str,
        state_root: Path | str,
    ) -> EntityRuntime:
        """Create a new independent persistent sovereign entity with its own private state root."""
        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        from jaeger_ai.core.entity.identity import resolve_entity_identity
        ident = resolve_entity_identity(
            state_root=root,
            default_name=display_name,
            instance_name=display_name.lower(),
        )
        runtime = EntityRuntime(
            state_root=root,
            identity=ident,
            mode=EntityRuntimeMode.TEST,
        )
        self.register_entity(runtime, agent_type=AgentType.PERSISTENT_SOVEREIGN)
        return runtime

    def get_entity(self, entity_id: str) -> EntityRuntime | None:
        with self._lock:
            return self._entities.get(entity_id)

    def list_entities(self) -> list[EntityIdentity]:
        with self._lock:
            return [rt.identity for rt in self._entities.values()]

    def set_trust(self, source_entity_id: str, target_entity_id: str, level: TrustLevel) -> None:
        with self._lock:
            self._trust_matrix[(source_entity_id, target_entity_id)] = level

    def get_trust(self, source_entity_id: str, target_entity_id: str) -> TrustLevel:
        with self._lock:
            return self._trust_matrix.get((source_entity_id, target_entity_id), TrustLevel.UNTRUSTED_EXTERNAL)

    # ── Shared Memory Collaboration Blackboard ──────────────────────────

    def set_shared(self, key: str, value: Any, *, author_entity_id: str = "") -> None:
        with self._lock:
            self._shared_memory[key] = {
                "value": value,
                "author": author_entity_id,
                "updated_at": time.time(),
            }

    def get_shared(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._shared_memory.get(key)
            return entry["value"] if entry else default

    # ── Inter-Agent Messaging ───────────────────────────────────────────

    def send_message(
        self,
        sender_id: str,
        recipient_id: str,
        payload: dict[str, Any],
        topic: str = "general",
    ) -> AgentMessage:
        msg = AgentMessage(
            sender_id=sender_id,
            recipient_id=recipient_id,
            topic=topic,
            payload=dict(payload),
        )
        with self._lock:
            self._inboxes[recipient_id].append(msg)
            logger.info("Routed message %s from %s to %s [topic: %s]", msg.message_id, sender_id, recipient_id, topic)
            return msg

    def read_inbox(self, entity_id: str, *, clear: bool = True) -> list[AgentMessage]:
        with self._lock:
            msgs = list(self._inboxes.get(entity_id, []))
            if clear:
                self._inboxes[entity_id].clear()
            return msgs

    # ── Delegation Lifecycle ────────────────────────────────────────────

    def delegate_task(
        self,
        parent_entity_id: str,
        assigned_to_entity_id: str,
        goal: str,
        capability_grants: tuple[str, ...] = (),
    ) -> DelegationTask:
        """Parent sovereign delegates a task to another entity with scoped capability grants."""
        with self._lock:
            if parent_entity_id not in self._entities:
                raise MultiAgentError(f"Parent entity {parent_entity_id} does not exist")
            if assigned_to_entity_id not in self._entities:
                raise MultiAgentError(f"Assigned entity {assigned_to_entity_id} does not exist")

            task = DelegationTask(
                parent_entity_id=parent_entity_id,
                assigned_to_entity_id=assigned_to_entity_id,
                goal=goal,
                capability_grants=capability_grants,
                status=DelegationStatus.RUNNING,
            )
            self._delegations[task.delegation_id] = task

            # Send delegation message to worker's inbox
            self.send_message(
                sender_id=parent_entity_id,
                recipient_id=assigned_to_entity_id,
                topic="delegation.assigned",
                payload={
                    "delegation_id": task.delegation_id,
                    "goal": goal,
                    "capability_grants": list(capability_grants),
                },
            )
            return task

    def complete_delegation(
        self,
        delegation_id: str,
        result: Any,
        *,
        error: str | None = None,
    ) -> DelegationTask:
        with self._lock:
            task = self._delegations.get(delegation_id)
            if not task:
                raise MultiAgentError(f"Delegation {delegation_id} not found")

            if task.status == DelegationStatus.CANCELLED:
                raise MultiAgentError(f"Cannot complete cancelled delegation {delegation_id}")

            task.status = DelegationStatus.FAILED if error else DelegationStatus.COMPLETED
            task.result = result
            task.error = error
            task.completed_at = time.time()

            # Notify parent
            self.send_message(
                sender_id=task.assigned_to_entity_id,
                recipient_id=task.parent_entity_id,
                topic="delegation.completed",
                payload={
                    "delegation_id": task.delegation_id,
                    "status": task.status.value,
                    "result": result,
                    "error": error,
                },
            )
            return task

    def cancel_delegation(self, delegation_id: str, reason: str = "Cancelled by parent") -> bool:
        """Parent cancels an in-flight delegation."""
        with self._lock:
            task = self._delegations.get(delegation_id)
            if not task:
                return False
            if task.status in (DelegationStatus.COMPLETED, DelegationStatus.FAILED):
                return False

            task.status = DelegationStatus.CANCELLED
            task.error = reason
            task.completed_at = time.time()

            # Send cancellation notification to worker
            self.send_message(
                sender_id=task.parent_entity_id,
                recipient_id=task.assigned_to_entity_id,
                topic="delegation.cancelled",
                payload={"delegation_id": task.delegation_id, "reason": reason},
            )
            logger.info("Cancelled delegation %s: %s", delegation_id, reason)
            return True

    def get_delegation(self, delegation_id: str) -> DelegationTask | None:
        with self._lock:
            return self._delegations.get(delegation_id)
