"""SQLite adapter for :class:`KnowledgeStore` — production cognitive persistence."""

from __future__ import annotations

import json
from typing import Any
from jaeger_agent.memory import memory as _mem
from jaeger_agent.memory import sqlite_store
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


def _safe_json_loads(val: Any, default: Any) -> Any:
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


def _claim_from_row(row: Any) -> Claim:
    return Claim(
        id=str(row["id"]),
        subject=str(row["subject"]),
        predicate=str(row["predicate"]),
        value=str(row["value"]),
        provenance=ProvenanceKind(row["provenance"]),
        source_id=str(row["source_id"]),
        confidence=float(row["confidence"]),
        status=str(row["status"]),
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        metadata=_safe_json_loads(row["metadata_json"], {}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _evidence_from_row(row: Any) -> Evidence:
    return Evidence(
        id=str(row["id"]),
        claim_id=row["claim_id"],
        belief_id=row["belief_id"],
        event_id=row["event_id"],
        source_type=str(row["source_type"]),
        snippet=str(row["snippet"] or ""),
        uri=row["uri"],
        created_at=str(row["created_at"]),
    )


def _belief_from_row(row: Any) -> Belief:
    return Belief(
        id=str(row["id"]),
        subject=str(row["subject"]),
        predicate=str(row["predicate"]),
        value=str(row["value"]),
        confidence=float(row["confidence"]),
        status=BeliefStatus(row["status"]),
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        superseded_by=row["superseded_by"],
        evidence_ids=_safe_json_loads(row["evidence_ids_json"], []),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _entity_from_row(row: Any) -> Entity:
    return Entity(
        id=str(row["id"]),
        name=str(row["name"]),
        kind=str(row["kind"]),
        aliases=_safe_json_loads(row["aliases_json"], []),
        attributes=_safe_json_loads(row["attributes_json"], {}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _rel_from_row(row: Any) -> Relationship:
    return Relationship(
        id=str(row["id"]),
        source_entity=str(row["source_entity"]),
        target_entity=str(row["target_entity"]),
        relation_type=str(row["relation_type"]),
        confidence=float(row["confidence"]),
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        metadata=_safe_json_loads(row["metadata_json"], {}),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class SqliteKnowledgeStore:
    """Delegates to the bound instance ``state.db`` (schema v5+)."""

    # ── MemoryStore implementation ─────────────────────────────────

    def remember(
        self,
        key: str,
        value: str,
        *,
        category: str | None = None,
        subject: str | None = None,
    ) -> None:
        _mem.remember(key, value, category=category, subject=subject)

    def recall(self, key: str, *, subject: str | None = None) -> str | None:
        return _mem.recall(key, subject=subject)

    def forget(self, key: str, *, subject: str | None = None) -> bool:
        return _mem.forget(key, subject=subject)

    def list_facts(self, *, subject: str | None = "user") -> dict[str, str]:
        return _mem.list_facts(subject=subject)

    def append_episodic(self, entry: dict[str, Any]) -> None:
        _mem.append_episodic(entry)

    def load_recent_turns(
        self, n: int = 5, *, session_key: str | None = None
    ) -> list[dict[str, str]]:
        return _mem.load_recent_turns(n, session_key=session_key)

    # ── ClaimStore implementation ──────────────────────────────────

    def add_claim(self, claim: Claim) -> Claim:
        conn = sqlite_store.connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO claims (
                id, subject, predicate, value, provenance, source_id,
                confidence, status, valid_from, valid_until, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim.id,
                claim.subject,
                claim.predicate,
                claim.value,
                claim.provenance.value if isinstance(claim.provenance, ProvenanceKind) else str(claim.provenance),
                claim.source_id,
                claim.confidence,
                claim.status,
                claim.valid_from,
                claim.valid_until,
                json.dumps(claim.metadata),
                claim.created_at,
                claim.updated_at,
            ),
        )
        conn.commit()
        return claim

    def get_claim(self, claim_id: str) -> Claim | None:
        conn = sqlite_store.connection()
        row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return _claim_from_row(row) if row else None

    def list_claims(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        provenance: ProvenanceKind | str | None = None,
        status: str | None = "valid",
    ) -> list[Claim]:
        conn = sqlite_store.connection()
        clauses: list[str] = []
        params: list[Any] = []

        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        if provenance is not None:
            p_val = provenance.value if isinstance(provenance, ProvenanceKind) else str(provenance)
            clauses.append("provenance = ?")
            params.append(p_val)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        query = "SELECT * FROM claims"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at"

        rows = conn.execute(query, params).fetchall()
        return [_claim_from_row(r) for r in rows]

    def invalidate_claim(self, claim_id: str) -> bool:
        conn = sqlite_store.connection()
        now = utc_now_iso()
        cur = conn.execute(
            "UPDATE claims SET status = 'invalid', updated_at = ? WHERE id = ?",
            (now, claim_id),
        )
        conn.commit()
        return cur.rowcount > 0

    # ── EvidenceStore implementation ───────────────────────────────

    def add_evidence(self, evidence: Evidence) -> Evidence:
        conn = sqlite_store.connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence (
                id, claim_id, belief_id, event_id, source_type, snippet, uri, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.id,
                evidence.claim_id,
                evidence.belief_id,
                evidence.event_id,
                evidence.source_type,
                evidence.snippet,
                evidence.uri,
                evidence.created_at,
            ),
        )
        conn.commit()
        return evidence

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        conn = sqlite_store.connection()
        row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        return _evidence_from_row(row) if row else None

    def list_evidence_for_claim(self, claim_id: str) -> list[Evidence]:
        conn = sqlite_store.connection()
        rows = conn.execute(
            "SELECT * FROM evidence WHERE claim_id = ? ORDER BY created_at",
            (claim_id,),
        ).fetchall()
        return [_evidence_from_row(r) for r in rows]

    def list_evidence_for_belief(self, belief_id: str) -> list[Evidence]:
        conn = sqlite_store.connection()
        b = self.get_belief(belief_id)
        if b is not None and b.evidence_ids:
            placeholders = ",".join("?" for _ in b.evidence_ids)
            rows = conn.execute(
                f"SELECT * FROM evidence WHERE id IN ({placeholders}) ORDER BY created_at",
                b.evidence_ids,
            ).fetchall()
            return [_evidence_from_row(r) for r in rows]
        rows = conn.execute(
            "SELECT * FROM evidence WHERE belief_id = ? ORDER BY created_at",
            (belief_id,),
        ).fetchall()
        return [_evidence_from_row(r) for r in rows]

    # ── BeliefStore implementation ─────────────────────────────────

    def save_belief(self, belief: Belief) -> Belief:
        conn = sqlite_store.connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO beliefs (
                id, subject, predicate, value, confidence, status,
                valid_from, valid_until, superseded_by, evidence_ids_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                belief.id,
                belief.subject,
                belief.predicate,
                belief.value,
                belief.confidence,
                belief.status.value if isinstance(belief.status, BeliefStatus) else str(belief.status),
                belief.valid_from,
                belief.valid_until,
                belief.superseded_by,
                json.dumps(belief.evidence_ids),
                belief.created_at,
                belief.updated_at,
            ),
        )
        conn.commit()
        return belief

    def get_belief(self, belief_id: str) -> Belief | None:
        conn = sqlite_store.connection()
        row = conn.execute("SELECT * FROM beliefs WHERE id = ?", (belief_id,)).fetchone()
        return _belief_from_row(row) if row else None

    def get_active_belief(self, subject: str, predicate: str) -> Belief | None:
        conn = sqlite_store.connection()
        row = conn.execute(
            "SELECT * FROM beliefs WHERE subject = ? AND predicate = ? AND status = 'active' "
            "ORDER BY updated_at DESC LIMIT 1",
            (subject, predicate),
        ).fetchone()
        return _belief_from_row(row) if row else None

    def list_beliefs(
        self,
        *,
        subject: str | None = None,
        predicate: str | None = None,
        status: BeliefStatus | str | None = BeliefStatus.ACTIVE,
    ) -> list[Belief]:
        conn = sqlite_store.connection()
        clauses: list[str] = []
        params: list[Any] = []

        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        if status is not None:
            st_val = status.value if isinstance(status, BeliefStatus) else str(status)
            clauses.append("status = ?")
            params.append(st_val)

        query = "SELECT * FROM beliefs"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at"

        rows = conn.execute(query, params).fetchall()
        return [_belief_from_row(r) for r in rows]

    def supersede_belief(self, old_belief_id: str, new_belief: Belief) -> Belief:
        now = utc_now_iso()
        conn = sqlite_store.connection()
        conn.execute(
            "UPDATE beliefs SET status = 'superseded', superseded_by = ?, updated_at = ? WHERE id = ?",
            (new_belief.id, now, old_belief_id),
        )
        self.save_belief(new_belief)
        conn.commit()
        return new_belief

    def retract_belief(self, belief_id: str) -> bool:
        now = utc_now_iso()
        conn = sqlite_store.connection()
        cur = conn.execute(
            "UPDATE beliefs SET status = 'retracted', updated_at = ? WHERE id = ?",
            (now, belief_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def rebuild_beliefs_from_claims(self, *, subject: str | None = None) -> list[Belief]:
        valid_claims = self.list_claims(subject=subject, status="valid")
        grouped: dict[tuple[str, str], list[Claim]] = {}
        for c in valid_claims:
            key = (c.subject, c.predicate)
            grouped.setdefault(key, []).append(c)

        conn = sqlite_store.connection()
        now = utc_now_iso()
        for (subj, pred) in grouped:
            conn.execute(
                "UPDATE beliefs SET status = 'superseded', updated_at = ? "
                "WHERE subject = ? AND predicate = ? AND status = 'active'",
                (now, subj, pred),
            )

        rebuilt: list[Belief] = []
        for (subj, pred), claims in grouped.items():
            latest = claims[-1]
            belief = Belief.create(
                subject=subj,
                predicate=pred,
                value=latest.value,
                confidence=latest.confidence,
                status=BeliefStatus.ACTIVE,
                valid_from=latest.valid_from,
                valid_until=latest.valid_until,
            )
            self.save_belief(belief)
            rebuilt.append(belief)
        conn.commit()
        return rebuilt

    # ── EntityStore implementation ─────────────────────────────────

    def save_entity(self, entity: Entity) -> Entity:
        conn = sqlite_store.connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO entities (
                id, name, kind, aliases_json, attributes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity.id,
                entity.name,
                entity.kind,
                json.dumps(entity.aliases),
                json.dumps(entity.attributes),
                entity.created_at,
                entity.updated_at,
            ),
        )
        conn.commit()
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        conn = sqlite_store.connection()
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return _entity_from_row(row) if row else None

    def find_entity(self, name_or_alias: str) -> Entity | None:
        target = name_or_alias.strip().lower()
        conn = sqlite_store.connection()
        rows = conn.execute("SELECT * FROM entities").fetchall()
        for r in rows:
            e = _entity_from_row(r)
            if e.name.strip().lower() == target:
                return e
            if any(a.strip().lower() == target for a in e.aliases):
                return e
        return None

    def list_entities(self, *, kind: str | None = None) -> list[Entity]:
        conn = sqlite_store.connection()
        if kind is None:
            rows = conn.execute("SELECT * FROM entities ORDER BY name").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM entities WHERE kind = ? ORDER BY name",
                (kind,),
            ).fetchall()
        return [_entity_from_row(r) for r in rows]

    def save_relationship(self, relationship: Relationship) -> Relationship:
        conn = sqlite_store.connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO relationships (
                id, source_entity, target_entity, relation_type,
                confidence, valid_from, valid_until, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relationship.id,
                relationship.source_entity,
                relationship.target_entity,
                relationship.relation_type,
                relationship.confidence,
                relationship.valid_from,
                relationship.valid_until,
                json.dumps(relationship.metadata),
                relationship.created_at,
                relationship.updated_at,
            ),
        )
        conn.commit()
        return relationship

    def list_relationships(
        self,
        *,
        source_entity: str | None = None,
        target_entity: str | None = None,
        relation_type: str | None = None,
    ) -> list[Relationship]:
        conn = sqlite_store.connection()
        clauses: list[str] = []
        params: list[Any] = []

        if source_entity is not None:
            clauses.append("source_entity = ?")
            params.append(source_entity)
        if target_entity is not None:
            clauses.append("target_entity = ?")
            params.append(target_entity)
        if relation_type is not None:
            clauses.append("relation_type = ?")
            params.append(relation_type)

        query = "SELECT * FROM relationships"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at"

        rows = conn.execute(query, params).fetchall()
        return [_rel_from_row(r) for r in rows]


__all__ = ["SqliteKnowledgeStore"]
