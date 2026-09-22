"""Domain definitions for the unified World-State Architecture (Workstream 7).

Epistemic Invariant:
    OBSERVATION != CLAIM != BELIEF != FACT
    "I observed X" != "I was told X" != "I infer X" != "I believe X"

Distinguishes:
- ENTITY: Structured actor, agent, device, project, or concept.
- OBSERVATION: Raw sensory/tool perception (not an automatic fact).
- EVIDENCE: Grounding trace tying claims/beliefs to observations or events.
- CLAIM: Stated proposition with confidence, provenance, and source.
- RELATIONSHIP: Directed typed connection between two entities.
- BELIEF: Synthesized active consensus held by the cognitive entity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import time
from typing import Any
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class EpistemicProvenance(str, Enum):
    """Epistemic origin of knowledge."""
    OBSERVED = "observed"      # Directly perceived from tool/sensor output
    TOLD = "told"              # Asserted by human or external communication
    INFERRED = "inferred"      # Deductive/inductive reasoning product
    BELIEVED = "believed"      # Synthesized world consensus
    PREDICTED = "predicted"    # Probabilistic forecast
    SYSTEM = "system"          # Ground-truth configuration or commissioning fact


class BeliefStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CONTRADICTED = "contradicted"
    RETRACTED = "retracted"


@dataclass(frozen=True)
class WorldEntity:
    """A persistent entity in the world graph."""
    entity_id: str
    name: str
    kind: str  # person, agent, project, device, tool, concept
    aliases: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorldObservation:
    """An empirical observation from a sensor, tool, or document. Not yet a fact."""
    observation_id: str
    sensor: str
    signals: dict[str, Any]
    salience: float = 0.5
    source_event_id: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorldEvidence:
    """Grounding link tying a claim or belief to an empirical observation or event."""
    evidence_id: str
    target_id: str  # claim_id or belief_id
    source_type: str  # observation, event, tool_call, document
    source_id: str
    snippet: str = ""
    uri: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorldClaim:
    """A proposition made by a source with explicit provenance and confidence."""
    claim_id: str
    subject: str
    predicate: str
    value: str
    provenance: EpistemicProvenance
    confidence: float = 1.0
    source_id: str = "operator"
    valid_from: float = field(default_factory=time.time)
    valid_until: float | None = None
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorldRelationship:
    """A directed, typed relationship between two entities."""
    relationship_id: str
    subject_entity_id: str
    relation: str  # leads, manages, owns, member_of, works_on, depends_on, located_at
    target_entity_id: str
    confidence: float = 1.0
    evidence_ids: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class WorldBelief:
    """An active cognitive projection synthesized from claims and grounded in evidence."""
    belief_id: str
    subject: str
    predicate: str
    value: str
    confidence: float = 1.0
    status: BeliefStatus = BeliefStatus.ACTIVE
    evidence_ids: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
