"""In-memory KnowledgeStore — the contract test reference implementation for cognitive data."""

from __future__ import annotations

from typing import Any
from jaeger_agent.memory.models import (
    Belief,
    BeliefStatus,
    Claim,
    Entity,
    Evidence,
    ProvenanceKind,
    Relationship,
    utc_now_iso,
)


class InMemoryKnowledgeStore:
    def __init__(self) -> None:
        # Legacy MemoryStore storage
        self._facts: dict[tuple[str, str], str] = {}
        self._episodic: list[dict[str, Any]] = []

        # Cognitive Knowledge storage
        self._claims: dict[str, Claim] = {}
        self._evidence: dict[str, Evidence] = {}
        self._beliefs: dict[str, Belief] = {}
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}

    # ── MemoryStore implementation ─────────────────────────────────

    def remember(
        self,
        key: str,
        value: str,
        *,
        category: str | None = None,
        subject: str | None = None,
    ) -> None:
        self._facts[(subject or "user", key)] = value

    def recall(self, key: str, *, subject: str | None = None) -> str | None:
        return self._facts.get((subject or "user", key))

    def forget(self, key: str, *, subject: str | None = None) -> bool:
        return self._facts.pop((subject or "user", key), None) is not None

    def list_facts(self, *, subject: str | None = "user") -> dict[str, str]:
        subj = subject or "user"
        return {k: v for (s, k), v in self._facts.items() if s == subj}

    def append_episodic(self, entry: dict[str, Any]) -> None:
        self._episodic.append(dict(entry))

    def load_recent_turns(
        self, n: int = 5, *, session_key: str | None = None
    ) -> list[dict[str, str]]:
        rows = self._episodic
        if session_key is not None:
            rows = [r for r in rows if r.get("session_key") == session_key]
        out: list[dict[str, str]] = []
        for row in rows[-n:]:
            out.append({
                "user": str(row.get("user") or ""),
                "answer": str(row.get("answer") or ""),
                "session_key": str(row.get("session_key") or ""),
            })
        return out

    # ── ClaimStore implementation ──────────────────────────────────

    def add_claim(self, claim: Claim) -> Claim:
        self._claims[claim.id] = claim
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def list_claims(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        provenance: ProvenanceKind | str | None = None,
        status: str | None = "valid",
    ) -> list[Claim]:
        prov = ProvenanceKind(provenance) if isinstance(provenance, str) else provenance
        results: list[Claim] = []
        for c in self._claims.values():
            if subject is not None and c.subject != subject:
                continue
            if predicate is not None and c.predicate != predicate:
                continue
            if prov is not None and c.provenance != prov:
                continue
            if status is not None and c.status != status:
                continue
            results.append(c)
        return sorted(results, key=lambda x: x.created_at)

    def invalidate_claim(self, claim_id: str) -> bool:
        c = self._claims.get(claim_id)
        if c is None:
            return False
        c.status = "invalid"
        c.updated_at = utc_now_iso()
        return True

    # ── EvidenceStore implementation ───────────────────────────────

    def add_evidence(self, evidence: Evidence) -> Evidence:
        self._evidence[evidence.id] = evidence
        return evidence

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self._evidence.get(evidence_id)

    def list_evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        return [e for e in self._evidence.values() if e.claim_id == claim_id]

    def list_evidence_for_belief(self, belief_id: str) -> list[Evidence]:
        b = self._beliefs.get(belief_id)
        if b is not None and b.evidence_ids:
            return [self._evidence[eid] for eid in b.evidence_ids if eid in self._evidence]
        return [e for e in self._evidence.values() if e.belief_id == belief_id]

    # ── BeliefStore implementation ─────────────────────────────────

    def save_belief(self, belief: Belief) -> Belief:
        self._beliefs[belief.id] = belief
        return belief

    def get_belief(self, belief_id: str) -> Belief | None:
        return self._beliefs.get(belief_id)

    def get_active_belief(self, subject: str, predicate: str) -> Belief | None:
        for b in self._beliefs.values():
            if b.subject == subject and b.predicate == predicate and b.status == BeliefStatus.ACTIVE:
                return b
        return None

    def list_beliefs(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        status: BeliefStatus | str | None = BeliefStatus.ACTIVE,
    ) -> list[Belief]:
        st = BeliefStatus(status) if isinstance(status, str) else status
        results: list[Belief] = []
        for b in self._beliefs.values():
            if subject is not None and b.subject != subject:
                continue
            if predicate is not None and b.predicate != predicate:
                continue
            if st is not None and b.status != st:
                continue
            results.append(b)
        return sorted(results, key=lambda x: x.created_at)

    def supersede_belief(self, old_belief_id: str, new_belief: Belief) -> Belief:
        old = self._beliefs.get(old_belief_id)
        if old is not None:
            old.status = BeliefStatus.SUPERSEDED
            old.superseded_by = new_belief.id
            old.updated_at = utc_now_iso()
        self.save_belief(new_belief)
        return new_belief

    def retract_belief(self, belief_id: str) -> bool:
        b = self._beliefs.get(belief_id)
        if b is None:
            return False
        b.status = BeliefStatus.RETRACTED
        b.updated_at = utc_now_iso()
        return True

    def rebuild_beliefs_from_claims(self, *, subject: str | None = None) -> list[Belief]:
        """Derived projection. Provenance rank, not last-write-wins."""
        from jaeger_agent.cognition.revision import revise_all

        valid_claims = self.list_claims(subject=subject, status="valid")
        rebuilt = revise_all(valid_claims)
        keys = {(b.subject, b.predicate) for b in rebuilt}
        for b in list(self._beliefs.values()):
            if (b.subject, b.predicate) in keys and b.status == BeliefStatus.ACTIVE:
                b.status = BeliefStatus.SUPERSEDED
                b.updated_at = utc_now_iso()
        for belief in rebuilt:
            self.save_belief(belief)
        return rebuilt

    # ── EntityStore implementation ─────────────────────────────────

    def save_entity(self, entity: Entity) -> Entity:
        self._entities[entity.id] = entity
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def find_entity(self, name_or_alias: str) -> Entity | None:
        target = name_or_alias.strip().lower()
        for e in self._entities.values():
            if e.name.strip().lower() == target:
                return e
            if any(a.strip().lower() == target for a in e.aliases):
                return e
        return None

    def list_entities(self, *, kind: str | None = None) -> list[Entity]:
        if kind is None:
            return list(self._entities.values())
        return [e for e in self._entities.values() if e.kind == kind]

    def save_relationship(self, relationship: Relationship) -> Relationship:
        self._relationships[relationship.id] = relationship
        return relationship

    def list_relationships(
        self,
        *,
        source_entity: str | None = None,
        target_entity: str | None = None,
        relation_type: str | None = None,
    ) -> list[Relationship]:
        results: list[Relationship] = []
        for r in self._relationships.values():
            if source_entity is not None and r.source_entity != source_entity:
                continue
            if target_entity is not None and r.target_entity != target_entity:
                continue
            if relation_type is not None and r.relation_type != relation_type:
                continue
            results.append(r)
        return results


__all__ = ["InMemoryKnowledgeStore"]
