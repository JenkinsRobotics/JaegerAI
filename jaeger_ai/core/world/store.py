"""Unified SQLite storage for World-State Architecture (Workstream 7).

Manages all persistent world-state data in <state_root>/knowledge.sqlite3:
- entities
- claims
- relationships
- observations
- evidence
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid

from .model import (
    BeliefStatus,
    EpistemicProvenance,
    WorldBelief,
    WorldClaim,
    WorldEntity,
    WorldEvidence,
    WorldObservation,
    WorldRelationship,
)


class SqliteWorldStore:
    """Unified store for the world-state graph, claims, and empirical observations."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS world_entities (
                    entity_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    attributes_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_claims (
                    claim_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_id TEXT NOT NULL,
                    valid_from REAL NOT NULL,
                    valid_until REAL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_relationships (
                    relationship_id TEXT PRIMARY KEY,
                    subject_entity_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    target_entity_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    FOREIGN KEY (subject_entity_id) REFERENCES world_entities(entity_id),
                    FOREIGN KEY (target_entity_id) REFERENCES world_entities(entity_id)
                );

                CREATE TABLE IF NOT EXISTS world_observations (
                    observation_id TEXT PRIMARY KEY,
                    sensor TEXT NOT NULL,
                    signals_json TEXT NOT NULL,
                    salience REAL NOT NULL,
                    source_event_id TEXT,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS world_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    uri TEXT,
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_claims_subj ON world_claims(subject);
                CREATE INDEX IF NOT EXISTS idx_claims_prov ON world_claims(provenance);
                CREATE INDEX IF NOT EXISTS idx_rel_subj ON world_relationships(subject_entity_id);
                CREATE INDEX IF NOT EXISTS idx_obs_sensor ON world_observations(sensor);
                """
            )

    # ── Entity Operations ──────────────────────────────────────────────

    def record_entity(
        self,
        name: str,
        kind: str,
        *,
        aliases: tuple[str, ...] = (),
        attributes: dict[str, Any] | None = None,
        entity_id: str | None = None,
    ) -> WorldEntity:
        eid = entity_id or f"ent_{uuid.uuid4().hex[:12]}"
        now = time.time()
        ent = WorldEntity(
            entity_id=eid,
            name=name.strip(),
            kind=kind.strip(),
            aliases=aliases,
            attributes=dict(attributes or {}),
            created_at=now,
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO world_entities (entity_id, name, kind, aliases_json, attributes_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity_id) DO UPDATE SET
                    name=excluded.name,
                    kind=excluded.kind,
                    aliases_json=excluded.aliases_json,
                    attributes_json=excluded.attributes_json
                """,
                (
                    ent.entity_id,
                    ent.name,
                    ent.kind,
                    json.dumps(list(ent.aliases)),
                    json.dumps(ent.attributes),
                    ent.created_at,
                ),
            )
        return ent

    def get_entity(self, entity_id: str) -> WorldEntity | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM world_entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if not row:
                return None
            return WorldEntity(
                entity_id=row["entity_id"],
                name=row["name"],
                kind=row["kind"],
                aliases=tuple(json.loads(row["aliases_json"])),
                attributes=json.loads(row["attributes_json"]),
                created_at=row["created_at"],
            )

    # ── Claim Operations ───────────────────────────────────────────────

    def record_claim(
        self,
        subject: str,
        predicate: str,
        value: str,
        provenance: EpistemicProvenance | str = EpistemicProvenance.TOLD,
        *,
        confidence: float = 1.0,
        source_id: str = "operator",
        claim_id: str | None = None,
    ) -> WorldClaim:
        cid = claim_id or f"clm_{uuid.uuid4().hex[:12]}"
        prov = EpistemicProvenance(provenance) if isinstance(provenance, str) else provenance
        now = time.time()
        claim = WorldClaim(
            claim_id=cid,
            subject=subject.strip(),
            predicate=predicate.strip(),
            value=str(value),
            provenance=prov,
            confidence=max(0.0, min(1.0, float(confidence))),
            source_id=source_id.strip(),
            valid_from=now,
            created_at=now,
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO world_claims (claim_id, subject, predicate, value, provenance, confidence, source_id, valid_from, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.claim_id,
                    claim.subject,
                    claim.predicate,
                    claim.value,
                    claim.provenance.value,
                    claim.confidence,
                    claim.source_id,
                    claim.valid_from,
                    claim.created_at,
                ),
            )
        return claim

    def query_claims(self, subject: str) -> list[WorldClaim]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM world_claims WHERE subject = ? ORDER BY created_at DESC", (subject,)
            ).fetchall()
            return [
                WorldClaim(
                    claim_id=r["claim_id"],
                    subject=r["subject"],
                    predicate=r["predicate"],
                    value=r["value"],
                    provenance=EpistemicProvenance(r["provenance"]),
                    confidence=r["confidence"],
                    source_id=r["source_id"],
                    valid_from=r["valid_from"],
                    valid_until=r["valid_until"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def list_recent_claims(self, limit: int = 20) -> list[WorldClaim]:
        """Claims still in force, newest first. An expired claim was withdrawn
        (``valid_until`` set) and must not come back as something believed."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM world_claims WHERE valid_until IS NULL OR valid_until > ? "
                "ORDER BY created_at DESC LIMIT ?",
                (time.time(), limit),
            ).fetchall()
            return [
                WorldClaim(
                    claim_id=r["claim_id"],
                    subject=r["subject"],
                    predicate=r["predicate"],
                    value=r["value"],
                    provenance=EpistemicProvenance(r["provenance"]),
                    confidence=r["confidence"],
                    source_id=r["source_id"],
                    valid_from=r["valid_from"],
                    valid_until=r["valid_until"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # ── Observation Operations ─────────────────────────────────────────

    def record_observation(
        self,
        sensor: str,
        signals: dict[str, Any],
        *,
        salience: float = 0.5,
        source_event_id: str | None = None,
        observation_id: str | None = None,
    ) -> WorldObservation:
        oid = observation_id or f"obs_{uuid.uuid4().hex[:12]}"
        now = time.time()
        obs = WorldObservation(
            observation_id=oid,
            sensor=sensor.strip(),
            signals=dict(signals or {}),
            salience=salience,
            source_event_id=source_event_id,
            created_at=now,
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO world_observations (observation_id, sensor, signals_json, salience, source_event_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.observation_id,
                    obs.sensor,
                    json.dumps(obs.signals),
                    obs.salience,
                    obs.source_event_id,
                    obs.created_at,
                ),
            )
        return obs

    # ── Relationship Operations ────────────────────────────────────────

    def record_relationship(
        self,
        subject_entity_id: str,
        relation: str,
        target_entity_id: str,
        *,
        confidence: float = 1.0,
        evidence_ids: tuple[str, ...] = (),
        relationship_id: str | None = None,
    ) -> WorldRelationship:
        rid = relationship_id or f"rel_{uuid.uuid4().hex[:12]}"
        now = time.time()
        rel = WorldRelationship(
            relationship_id=rid,
            subject_entity_id=subject_entity_id,
            relation=relation.strip(),
            target_entity_id=target_entity_id,
            confidence=confidence,
            evidence_ids=evidence_ids,
            created_at=now,
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO world_relationships (relationship_id, subject_entity_id, relation, target_entity_id, confidence, evidence_ids_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rel.relationship_id,
                    rel.subject_entity_id,
                    rel.relation,
                    rel.target_entity_id,
                    rel.confidence,
                    json.dumps(list(rel.evidence_ids)),
                    rel.created_at,
                ),
            )
        return rel

    # ── Evidence Operations ────────────────────────────────────────────

    def link_evidence(
        self,
        target_id: str,
        source_type: str,
        source_id: str,
        snippet: str = "",
        uri: str | None = None,
        evidence_id: str | None = None,
    ) -> WorldEvidence:
        evid = evidence_id or f"evi_{uuid.uuid4().hex[:12]}"
        now = time.time()
        evi = WorldEvidence(
            evidence_id=evid,
            target_id=target_id,
            source_type=source_type,
            source_id=source_id,
            snippet=snippet,
            uri=uri,
            created_at=now,
        )
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO world_evidence (evidence_id, target_id, source_type, source_id, snippet, uri, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evi.evidence_id,
                    evi.target_id,
                    evi.source_type,
                    evi.source_id,
                    evi.snippet,
                    evi.uri,
                    evi.created_at,
                ),
            )
        return evi
