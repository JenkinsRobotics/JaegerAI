"""Tests for unified World-State Architecture (Workstream 7).

Verifies Epistemic Invariants:
1. OBSERVATION != CLAIM != BELIEF != FACT
2. Raw observations do not automatically mutate into accepted claims without evidence.
3. Directed relationships link typed entities.
4. Evidence links claims/beliefs back to observation/sensor sources.
5. SemanticMemory delegates authoritatively to SqliteWorldStore (<state_root>/knowledge.sqlite3).
"""
import tempfile
from pathlib import Path
import pytest

from jaeger_ai.core.world.model import (
    BeliefStatus,
    EpistemicProvenance,
    WorldBelief,
    WorldClaim,
    WorldEntity,
    WorldEvidence,
    WorldObservation,
    WorldRelationship,
)
from jaeger_ai.core.world.store import SqliteWorldStore
from jaeger_ai.core.entity.memory import SemanticMemory


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "knowledge.sqlite3"
        yield SqliteWorldStore(db_path)


def test_entity_creation_and_retrieval(temp_store: SqliteWorldStore):
    ent = temp_store.record_entity(
        name="Jaeger",
        kind="agent",
        aliases=("jaeger-1", "resident-agent"),
        attributes={"runtime": "python", "version": "1.0"},
    )
    assert ent.name == "Jaeger"
    assert ent.kind == "agent"
    assert "resident-agent" in ent.aliases

    retrieved = temp_store.get_entity(ent.entity_id)
    assert retrieved is not None
    assert retrieved.name == "Jaeger"
    assert retrieved.attributes.get("runtime") == "python"


def test_observation_is_not_automatic_claim(temp_store: SqliteWorldStore):
    """An empirical observation does not automatically create or become a verified claim."""
    obs = temp_store.record_observation(
        sensor="camera_front",
        signals={"faces_detected": 1, "confidence": 0.82},
        salience=0.9,
    )
    assert obs.observation_id.startswith("obs_")
    assert obs.sensor == "camera_front"

    # Searching claims returns nothing - observation has not been turned into a claim
    claims = temp_store.query_claims("camera_front")
    assert len(claims) == 0


def test_claim_with_provenance_and_evidence(temp_store: SqliteWorldStore):
    """Claims must store explicit provenance, confidence, and can be linked to evidence."""
    # 1. Raw observation
    obs = temp_store.record_observation(
        sensor="terminal_stdout",
        signals={"line": "build succeeded in 4.2s"},
    )

    # 2. Claim derived with OBSERVED provenance
    claim = temp_store.record_claim(
        subject="project_build",
        predicate="status",
        value="success",
        provenance=EpistemicProvenance.OBSERVED,
        confidence=0.98,
        source_id=obs.sensor,
    )
    assert claim.provenance == EpistemicProvenance.OBSERVED
    assert claim.confidence == 0.98

    # 3. Grounding evidence link
    evi = temp_store.link_evidence(
        target_id=claim.claim_id,
        source_type="observation",
        source_id=obs.observation_id,
        snippet="build succeeded in 4.2s",
    )
    assert evi.target_id == claim.claim_id
    assert evi.source_id == obs.observation_id


def test_relationships_link_entities(temp_store: SqliteWorldStore):
    """Directed relationships link entities with confidence and evidence."""
    user = temp_store.record_entity("Alice", "person")
    project = temp_store.record_entity("JaegerAI", "project")

    rel = temp_store.record_relationship(
        subject_entity_id=user.entity_id,
        relation="maintains",
        target_entity_id=project.entity_id,
        confidence=1.0,
    )
    assert rel.relation == "maintains"
    assert rel.subject_entity_id == user.entity_id
    assert rel.target_entity_id == project.entity_id


def test_semantic_memory_delegation():
    """SemanticMemory delegates seamlessly to SqliteWorldStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        sem_mem = SemanticMemory(state_root)

        res = sem_mem.record_claim(
            subject="operator",
            predicate="preferred_shell",
            value="zsh",
            confidence=0.95,
        )
        assert res["status"] == "recorded"
        assert res["subject"] == "operator"

        claims = sem_mem.query_claims("operator")
        assert len(claims) == 1
        assert claims[0]["predicate"] == "preferred_shell"
        assert claims[0]["value"] == "zsh"

        recent = sem_mem.list_recent()
        assert len(recent) == 1
        assert recent[0]["subject"] == "operator"

        # Verify underlying world store matches
        db_claims = sem_mem.world_store.query_claims("operator")
        assert len(db_claims) == 1
        assert db_claims[0].value == "zsh"


def test_a_withdrawn_claim_is_not_recalled(temp_store: SqliteWorldStore):
    """Recall ignored ``valid_until``, so a withdrawn claim (the audit's
    ``user.remembered_word=voice``) kept being fed to the model as belief."""
    import sqlite3
    import time

    kept = temp_store.record_claim("user", "audit_memory_token", "AUDIT-MEMORY-NOVA-7319")
    withdrawn = temp_store.record_claim("user", "remembered_word", "voice")
    with sqlite3.connect(temp_store.db_path) as conn:
        conn.execute("UPDATE world_claims SET valid_until=? WHERE claim_id=?",
                     (time.time() - 1, withdrawn.claim_id))

    recalled = [c.claim_id for c in temp_store.list_recent_claims(10)]

    assert kept.claim_id in recalled
    assert withdrawn.claim_id not in recalled
