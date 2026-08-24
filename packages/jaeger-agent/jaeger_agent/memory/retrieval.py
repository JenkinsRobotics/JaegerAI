"""Cognitive retrieval, contradiction detection, and provenance explanation."""

from __future__ import annotations

from typing import Any
from jaeger_agent.memory.knowledge_port import (
    BeliefStore,
    ClaimStore,
    CognitiveRetriever,
    EntityStore,
    EvidenceStore,
    KnowledgeStore,
)
from jaeger_agent.memory.models import Belief, BeliefStatus, Claim, Entity, ProvenanceKind


class KnowledgeRetriever(CognitiveRetriever):
    """Cognitive retrieval engine built over modular stores."""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def query_active_beliefs(
        self,
        subject: str,
        predicate: str | None = None,
        as_of: str | None = None,
    ) -> list[Belief]:
        """Query active beliefs for a subject, with optional temporal point-in-time filtering."""
        beliefs = self.store.list_beliefs(subject=subject, predicate=predicate, status=BeliefStatus.ACTIVE)
        if as_of is None:
            return beliefs

        # Point-in-time temporal validity filtering
        valid_at_time: list[Belief] = []
        for b in beliefs:
            if b.valid_from and b.valid_from > as_of:
                continue
            if b.valid_until and b.valid_until < as_of:
                continue
            valid_at_time.append(b)
        return valid_at_time

    def detect_contradictions(
        self,
        subject: str,
        predicate: str | None = None,
    ) -> list[dict[str, Any]]:
        """Identify conflicting claims or disputed assertions for a given subject and predicate."""
        claims = self.store.list_claims(subject=subject, predicate=predicate, status="valid")
        grouped: dict[tuple[str, str], list[Claim]] = {}
        for c in claims:
            grouped.setdefault((c.subject, c.predicate), []).append(c)

        contradictions: list[dict[str, Any]] = []
        for (subj, pred), claim_list in grouped.items():
            distinct_values = {c.value for c in claim_list}
            if len(distinct_values) > 1:
                beliefs = self.store.list_beliefs(subject=subj, predicate=pred, status=None)
                contradictions.append({
                    "subject": subj,
                    "predicate": pred,
                    "conflicting_values": list(distinct_values),
                    "claims": [
                        {
                            "id": c.id,
                            "value": c.value,
                            "provenance": c.provenance.value if isinstance(c.provenance, ProvenanceKind) else str(c.provenance),
                            "source_id": c.source_id,
                            "confidence": c.confidence,
                            "created_at": c.created_at,
                        }
                        for c in claim_list
                    ],
                    "beliefs": [
                        {
                            "id": b.id,
                            "value": b.value,
                            "status": b.status.value if isinstance(b.status, BeliefStatus) else str(b.status),
                            "confidence": b.confidence,
                        }
                        for b in beliefs
                    ],
                })
        return contradictions

    def get_entity_knowledge(
        self,
        name_or_alias: str,
    ) -> dict[str, Any] | None:
        """Retrieve aggregated entity graph profile, including attributes, relationships, and active beliefs."""
        entity = self.store.find_entity(name_or_alias)
        if entity is None:
            return None

        # Outgoing and incoming relationships
        outgoing = self.store.list_relationships(source_entity=entity.name)
        incoming = self.store.list_relationships(target_entity=entity.name)

        # Beliefs directly attached to this entity
        beliefs = self.store.list_beliefs(subject=entity.name, status=BeliefStatus.ACTIVE)

        return {
            "entity": {
                "id": entity.id,
                "name": entity.name,
                "kind": entity.kind,
                "aliases": entity.aliases,
                "attributes": entity.attributes,
                "created_at": entity.created_at,
                "updated_at": entity.updated_at,
            },
            "outgoing_relationships": [
                {
                    "id": r.id,
                    "target": r.target_entity,
                    "relation_type": r.relation_type,
                    "confidence": r.confidence,
                    "metadata": r.metadata,
                }
                for r in outgoing
            ],
            "incoming_relationships": [
                {
                    "id": r.id,
                    "source": r.source_entity,
                    "relation_type": r.relation_type,
                    "confidence": r.confidence,
                    "metadata": r.metadata,
                }
                for r in incoming
            ],
            "beliefs": {b.predicate: b.value for b in beliefs},
        }

    def explain_provenance(self, claim_or_belief_id: str) -> dict[str, Any] | None:
        """Generate an explainability payload detailing the evidence chain and epistemic origin."""
        # Check claim
        claim = self.store.get_claim(claim_or_belief_id)
        if claim is not None:
            evidence = self.store.list_evidence_for_claim(claim.id)
            return {
                "type": "claim",
                "id": claim.id,
                "subject": claim.subject,
                "predicate": claim.predicate,
                "value": claim.value,
                "provenance": claim.provenance.value if isinstance(claim.provenance, ProvenanceKind) else str(claim.provenance),
                "source_id": claim.source_id,
                "confidence": claim.confidence,
                "status": claim.status,
                "created_at": claim.created_at,
                "evidence": [
                    {
                        "id": e.id,
                        "source_type": e.source_type,
                        "snippet": e.snippet,
                        "uri": e.uri,
                        "event_id": e.event_id,
                    }
                    for e in evidence
                ],
            }

        # Check belief
        belief = self.store.get_belief(claim_or_belief_id)
        if belief is not None:
            evidence = self.store.list_evidence_for_belief(belief.id)
            return {
                "type": "belief",
                "id": belief.id,
                "subject": belief.subject,
                "predicate": belief.predicate,
                "value": belief.value,
                "status": belief.status.value if isinstance(belief.status, BeliefStatus) else str(belief.status),
                "confidence": belief.confidence,
                "superseded_by": belief.superseded_by,
                "created_at": belief.created_at,
                "evidence": [
                    {
                        "id": e.id,
                        "source_type": e.source_type,
                        "snippet": e.snippet,
                        "uri": e.uri,
                        "event_id": e.event_id,
                    }
                    for e in evidence
                ],
            }

        return None


__all__ = ["KnowledgeRetriever"]
