"""Domain models for persistent cognitive data architecture.

Separates:
  - Authoritative event (immutable raw action/turn/sensory records)
  - Claim (stated proposition with provenance and source)
  - Evidence (grounding links tying claims/beliefs to events/documents)
  - Derived belief (active cognitive projection synthesized from claims)
  - Entity (structured actor, workspace, tool, concept)
  - Relationship (directed typed connections between entities)

Invariant:
  "I observed X" != "I was told X" != "I infer X" != "I believe X" != "I predict X"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProvenanceKind(str, Enum):
    """The epistemic origin of an assertion."""
    OBSERVED = "observed"    # Directly observed event (tool output, sensor reading, system telemetry)
    TOLD = "told"            # User statement or external communication ("I was told X")
    INFERRED = "inferred"    # Deductive/inductive inference made by reasoning engine ("I infer X")
    BELIEVED = "believed"    # Synthesized persistent belief or world-model consensus ("I believe X")
    PREDICTED = "predicted"  # Probabilistic forecast or anticipated outcome ("I predict X")
    SYSTEM = "system"        # Hardwired or system configuration fact


class BeliefStatus(str, Enum):
    """The lifecycle state of a derived belief."""
    ACTIVE = "active"              # Currently held active belief
    SUPERSEDED = "superseded"      # Replaced by a more recent/accurate belief
    CONTRADICTED = "contradicted"  # Subject to active dispute/contradiction
    RETRACTED = "retracted"        # Explicitly forgotten, deleted, or retracted


@dataclass(slots=True)
class Claim:
    """A stated proposition from a specific source with provenance and validity."""
    id: str
    subject: str
    predicate: str
    value: str
    provenance: ProvenanceKind
    source_id: str = "user"
    confidence: float = 1.0
    status: str = "valid"
    valid_from: str | None = None
    valid_until: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        subject: str,
        predicate: str,
        value: str,
        provenance: ProvenanceKind | str,
        *,
        source_id: str = "user",
        confidence: float = 1.0,
        valid_from: str | None = None,
        valid_until: str | None = None,
        metadata: dict[str, Any] | None = None,
        claim_id: str | None = None,
    ) -> Claim:
        now = utc_now_iso()
        prov = ProvenanceKind(provenance) if isinstance(provenance, str) else provenance
        return cls(
            id=claim_id or uuid.uuid4().hex[:16],
            subject=subject.strip(),
            predicate=predicate.strip(),
            value=value,
            provenance=prov,
            source_id=source_id.strip() or "user",
            confidence=max(0.0, min(1.0, float(confidence))),
            status="valid",
            valid_from=valid_from or now,
            valid_until=valid_until,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )


@dataclass(slots=True)
class Evidence:
    """Grounding links tying claims or beliefs back to authoritative sources."""
    id: str
    claim_id: str | None = None
    belief_id: str | None = None
    event_id: str | None = None
    source_type: str = "turn"  # "turn", "tool_call", "audit", "document", "external"
    snippet: str = ""
    uri: str | None = None
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        *,
        claim_id: str | None = None,
        belief_id: str | None = None,
        event_id: str | None = None,
        source_type: str = "turn",
        snippet: str = "",
        uri: str | None = None,
        evidence_id: str | None = None,
    ) -> Evidence:
        return cls(
            id=evidence_id or uuid.uuid4().hex[:16],
            claim_id=claim_id,
            belief_id=belief_id,
            event_id=event_id,
            source_type=source_type,
            snippet=snippet,
            uri=uri,
            created_at=utc_now_iso(),
        )


@dataclass(slots=True)
class Belief:
    """An active cognitive projection synthesized from claims and evidence."""
    id: str
    subject: str
    predicate: str
    value: str
    confidence: float = 1.0
    status: BeliefStatus = BeliefStatus.ACTIVE
    valid_from: str | None = None
    valid_until: str | None = None
    superseded_by: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        subject: str,
        predicate: str,
        value: str,
        *,
        confidence: float = 1.0,
        status: BeliefStatus | str = BeliefStatus.ACTIVE,
        valid_from: str | None = None,
        valid_until: str | None = None,
        evidence_ids: list[str] | None = None,
        belief_id: str | None = None,
    ) -> Belief:
        now = utc_now_iso()
        st = BeliefStatus(status) if isinstance(status, str) else status
        return cls(
            id=belief_id or uuid.uuid4().hex[:16],
            subject=subject.strip(),
            predicate=predicate.strip(),
            value=value,
            confidence=max(0.0, min(1.0, float(confidence))),
            status=st,
            valid_from=valid_from or now,
            valid_until=valid_until,
            superseded_by=None,
            evidence_ids=list(evidence_ids or []),
            created_at=now,
            updated_at=now,
        )


@dataclass(slots=True)
class Entity:
    """Structured representation of a person, tool, workspace, or domain entity."""
    id: str
    name: str
    kind: str = "concept"  # "person", "project", "tool", "workspace", "concept", "device"
    aliases: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        name: str,
        *,
        kind: str = "concept",
        aliases: list[str] | None = None,
        attributes: dict[str, Any] | None = None,
        entity_id: str | None = None,
    ) -> Entity:
        now = utc_now_iso()
        return cls(
            id=entity_id or uuid.uuid4().hex[:16],
            name=name.strip(),
            kind=kind.strip(),
            aliases=list(aliases or []),
            attributes=dict(attributes or {}),
            created_at=now,
            updated_at=now,
        )


@dataclass(slots=True)
class Relationship:
    """A directed, typed connection between two entities."""
    id: str
    source_entity: str
    target_entity: str
    relation_type: str
    confidence: float = 1.0
    valid_from: str | None = None
    valid_until: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def create(
        cls,
        source_entity: str,
        target_entity: str,
        relation_type: str,
        *,
        confidence: float = 1.0,
        valid_from: str | None = None,
        valid_until: str | None = None,
        metadata: dict[str, Any] | None = None,
        relationship_id: str | None = None,
    ) -> Relationship:
        now = utc_now_iso()
        return cls(
            id=relationship_id or uuid.uuid4().hex[:16],
            source_entity=source_entity.strip(),
            target_entity=target_entity.strip(),
            relation_type=relation_type.strip(),
            confidence=max(0.0, min(1.0, float(confidence))),
            valid_from=valid_from or now,
            valid_until=valid_until,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )


__all__ = [
    "ProvenanceKind",
    "BeliefStatus",
    "Claim",
    "Evidence",
    "Belief",
    "Entity",
    "Relationship",
    "utc_now_iso",
]
