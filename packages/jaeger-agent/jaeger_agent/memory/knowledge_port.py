"""KnowledgePort — replaceable persistence protocols for cognitive memory.

Defines the interfaces for:
  - Claims (propositions with provenance)
  - Evidence (grounding links)
  - Beliefs (active synthesized projections)
  - Entities and Relationships (structured world model)
  - KnowledgeStore (unification of MemoryStore + Cognitive layer)
  - CognitiveRetriever (retrieval and explanation interfaces)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from jaeger_agent.memory.models import (
    Belief,
    BeliefStatus,
    Claim,
    Entity,
    Evidence,
    ProvenanceKind,
    Relationship,
)
from jaeger_agent.memory.port import MemoryStore


@runtime_checkable
class ClaimStore(Protocol):
    """Contract for storing and querying assertions/claims with provenance."""

    def add_claim(self, claim: Claim) -> Claim: ...

    def get_claim(self, claim_id: str) -> Claim | None: ...

    def list_claims(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        provenance: ProvenanceKind | str | None = None,
        status: str | None = "valid",
    ) -> list[Claim]: ...

    def invalidate_claim(self, claim_id: str) -> bool: ...


@runtime_checkable
class EvidenceStore(Protocol):
    """Contract for storing and linking evidence."""

    def add_evidence(self, evidence: Evidence) -> Evidence: ...

    def get_evidence(self, evidence_id: str) -> Evidence | None: ...

    def list_evidence_for_claim(self, claim_id: str) -> list[Evidence]: ...

    def list_evidence_for_belief(self, belief_id: str) -> list[Evidence]: ...


@runtime_checkable
class BeliefStore(Protocol):
    """Contract for managing derived active beliefs and their lifecycles."""

    def save_belief(self, belief: Belief) -> Belief: ...

    def get_belief(self, belief_id: str) -> Belief | None: ...

    def get_active_belief(self, subject: str, predicate: str) -> Belief | None: ...

    def list_beliefs(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        status: BeliefStatus | str | None = BeliefStatus.ACTIVE,
    ) -> list[Belief]: ...

    def supersede_belief(self, old_belief_id: str, new_belief: Belief) -> Belief: ...

    def retract_belief(self, belief_id: str) -> bool: ...

    def rebuild_beliefs_from_claims(self, *, subject: str | None = None) -> list[Belief]: ...


@runtime_checkable
class EntityStore(Protocol):
    """Contract for storing entities, aliases, attributes, and relationships."""

    def save_entity(self, entity: Entity) -> Entity: ...

    def get_entity(self, entity_id: str) -> Entity | None: ...

    def find_entity(self, name_or_alias: str) -> Entity | None: ...

    def list_entities(self, *, kind: str | None = None) -> list[Entity]: ...

    def save_relationship(self, relationship: Relationship) -> Relationship: ...

    def list_relationships(
        self,
        *,
        source_entity: str | None = None,
        target_entity: str | None = None,
        relation_type: str | None = None,
    ) -> list[Relationship]: ...


@runtime_checkable
class KnowledgeStore(MemoryStore, ClaimStore, EvidenceStore, BeliefStore, EntityStore, Protocol):
    """Unified contract combining legacy MemoryStore with cognitive data architecture."""
    ...


@runtime_checkable
class CognitiveRetriever(Protocol):
    """Contract for multi-modal cognitive retrieval and contradiction reasoning."""

    def query_active_beliefs(
        self,
        subject: str,
        predicate: str | None = None,
        as_of: str | None = None,
    ) -> list[Belief]: ...

    def detect_contradictions(
        self,
        subject: str,
        predicate: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_entity_knowledge(
        self,
        name_or_alias: str,
    ) -> dict[str, Any] | None: ...


__all__ = [
    "ClaimStore",
    "EvidenceStore",
    "BeliefStore",
    "EntityStore",
    "KnowledgeStore",
    "CognitiveRetriever",
]
