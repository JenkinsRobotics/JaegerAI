"""Contract tests for KnowledgeStore implementations.

Parametrized across InMemoryKnowledgeStore and SqliteKnowledgeStore to verify
complete behavioral parity and adherence to the cognitive data architecture contract.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from jaeger_agent.memory import sqlite_store
from jaeger_agent.memory.in_memory_knowledge import InMemoryKnowledgeStore
from jaeger_agent.memory.knowledge_port import KnowledgeStore
from jaeger_agent.memory.models import (
    Belief,
    BeliefStatus,
    Claim,
    Entity,
    Evidence,
    ProvenanceKind,
    Relationship,
)
from jaeger_agent.memory.retrieval import KnowledgeRetriever
from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path) -> KnowledgeStore:
    if request.param == "memory":
        yield InMemoryKnowledgeStore()
        return
    if request.param == "sqlite":
        layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / "memory")
        layout.memory_dir.mkdir(parents=True, exist_ok=True)
        sqlite_store.bind(layout)
        yield SqliteKnowledgeStore()
        sqlite_store.close()
        return
    raise AssertionError(request.param)


def test_store_satisfies_protocol(store):
    assert isinstance(store, KnowledgeStore)


def test_provenance_invariants(store):
    # Invariant: "I observed X" != "I was told X" != "I infer X" != "I believe X" != "I predict X"
    assert ProvenanceKind.OBSERVED.value != ProvenanceKind.TOLD.value
    assert ProvenanceKind.TOLD.value != ProvenanceKind.INFERRED.value
    assert ProvenanceKind.INFERRED.value != ProvenanceKind.BELIEVED.value
    assert ProvenanceKind.BELIEVED.value != ProvenanceKind.PREDICTED.value

    # Store claims with explicit provenance
    c_obs = Claim.create("sensor", "temperature", "22C", ProvenanceKind.OBSERVED)
    c_told = Claim.create("sensor", "temperature", "25C", ProvenanceKind.TOLD)
    c_inf = Claim.create("sensor", "weather", "comfortable", ProvenanceKind.INFERRED)

    store.add_claim(c_obs)
    store.add_claim(c_told)
    store.add_claim(c_inf)

    # Filter by provenance
    obs_claims = store.list_claims(provenance=ProvenanceKind.OBSERVED)
    assert len(obs_claims) == 1
    assert obs_claims[0].value == "22C"

    told_claims = store.list_claims(provenance=ProvenanceKind.TOLD)
    assert len(told_claims) == 1
    assert told_claims[0].value == "25C"


def test_claim_lifecycle(store):
    claim = Claim.create("user", "favorite_editor", "neovim", ProvenanceKind.TOLD, confidence=0.95)
    store.add_claim(claim)

    fetched = store.get_claim(claim.id)
    assert fetched is not None
    assert fetched.subject == "user"
    assert fetched.predicate == "favorite_editor"
    assert fetched.value == "neovim"
    assert fetched.confidence == 0.95
    assert fetched.status == "valid"

    # Invalidate claim
    assert store.invalidate_claim(claim.id) is True
    assert store.get_claim(claim.id).status == "invalid"
    assert len(store.list_claims(subject="user", status="valid")) == 0


def test_evidence_grounding(store):
    claim = Claim.create("system", "kernel", "Darwin 24.0", ProvenanceKind.OBSERVED)
    store.add_claim(claim)

    ev = Evidence.create(
        claim_id=claim.id,
        source_type="tool_call",
        snippet="uname -a returned Darwin 24.0.0",
        uri="tool://run_shell/output/42",
    )
    store.add_evidence(ev)

    ev_list = store.list_evidence_for_claim(claim.id)
    assert len(ev_list) == 1
    assert ev_list[0].snippet == "uname -a returned Darwin 24.0.0"
    assert ev_list[0].source_type == "tool_call"


def test_belief_lifecycle_and_supersession(store):
    b1 = Belief.create("user", "preferred_model", "claude-3.5-sonnet", confidence=0.9)
    store.save_belief(b1)

    active = store.get_active_belief("user", "preferred_model")
    assert active is not None
    assert active.value == "claude-3.5-sonnet"

    # Supersede with a newer belief
    b2 = Belief.create("user", "preferred_model", "gemini-2.0-flash", confidence=0.95)
    store.supersede_belief(b1.id, b2)

    old = store.get_belief(b1.id)
    assert old.status == BeliefStatus.SUPERSEDED
    assert old.superseded_by == b2.id

    new_active = store.get_active_belief("user", "preferred_model")
    assert new_active is not None
    assert new_active.id == b2.id
    assert new_active.value == "gemini-2.0-flash"


def test_belief_retraction_and_forgetting(store):
    b = Belief.create("user", "temporary_token", "secret123")
    store.save_belief(b)
    assert store.get_active_belief("user", "temporary_token") is not None

    assert store.retract_belief(b.id) is True
    assert store.get_belief(b.id).status == BeliefStatus.RETRACTED
    assert store.get_active_belief("user", "temporary_token") is None


def test_entity_and_relationship_graph(store):
    alice = Entity.create("Alice", kind="person", aliases=["Ali", "A.J."], attributes={"role": "Lead"})
    ares = Entity.create("ARES", kind="project", aliases=["ares-core"], attributes={"tier": "UI/Gov"})

    store.save_entity(alice)
    store.save_entity(ares)

    assert store.find_entity("Alice") is not None
    assert store.find_entity("Ali") is not None
    assert store.find_entity("ares-core") is not None

    rel = Relationship.create("Alice", "ARES", "owns", confidence=1.0, metadata={"since": "2026"})
    store.save_relationship(rel)

    rels = store.list_relationships(source_entity="Alice")
    assert len(rels) == 1
    assert rels[0].target_entity == "ARES"
    assert rels[0].relation_type == "owns"


def test_projection_rebuild_from_claims(store):
    """Observed outranks a later told claim. Not last-write-wins."""
    c1 = Claim.create("user", "shell", "bash", ProvenanceKind.OBSERVED)
    c2 = Claim.create("user", "shell", "zsh", ProvenanceKind.TOLD)
    store.add_claim(c1)
    store.add_claim(c2)

    rebuilt = store.rebuild_beliefs_from_claims(subject="user")
    assert len(rebuilt) == 1
    assert rebuilt[0].predicate == "shell"
    assert rebuilt[0].value == "bash"
    assert rebuilt[0].status == BeliefStatus.ACTIVE
    assert store.get_active_belief("user", "shell").value == "bash"


def test_same_rank_conflict_is_contradicted_not_last_write(store):
    store.add_claim(Claim.create("user", "shell", "bash", ProvenanceKind.TOLD))
    store.add_claim(Claim.create("user", "shell", "zsh", ProvenanceKind.TOLD))
    rebuilt = store.rebuild_beliefs_from_claims(subject="user")
    assert rebuilt[0].status == BeliefStatus.CONTRADICTED
    assert store.get_active_belief("user", "shell") is None


def test_retriever_contradiction_detection(store):
    c1 = Claim.create("agent", "mode", "autonomous", ProvenanceKind.TOLD)
    c2 = Claim.create("agent", "mode", "supervised", ProvenanceKind.OBSERVED)
    store.add_claim(c1)
    store.add_claim(c2)

    retriever = KnowledgeRetriever(store)
    contradictions = retriever.detect_contradictions(subject="agent", predicate="mode")
    assert len(contradictions) == 1
    assert contradictions[0]["subject"] == "agent"
    assert contradictions[0]["predicate"] == "mode"
    assert set(contradictions[0]["conflicting_values"]) == {"autonomous", "supervised"}


def test_retriever_entity_knowledge_and_provenance(store):
    bob = Entity.create("Bob", kind="person", aliases=["Bobby"], attributes={"team": "Core"})
    store.save_entity(bob)
    store.save_relationship(Relationship.create("Bob", "JaegerAI", "maintains"))
    b = Belief.create("Bob", "location", "London")
    store.save_belief(b)

    retriever = KnowledgeRetriever(store)
    info = retriever.get_entity_knowledge("Bobby")
    assert info is not None
    assert info["entity"]["name"] == "Bob"
    assert len(info["outgoing_relationships"]) == 1
    assert info["outgoing_relationships"][0]["target"] == "JaegerAI"
    assert info["beliefs"]["location"] == "London"

    expl = retriever.explain_provenance(b.id)
    assert expl is not None
    assert expl["type"] == "belief"
    assert expl["value"] == "London"


def test_temporal_validity_filtering(store):
    b1 = Belief.create("org", "lead", "Alice", valid_from="2025-01-01T00:00:00Z", valid_until="2025-12-31T23:59:59Z")
    b2 = Belief.create("org", "lead", "Bob", valid_from="2026-01-01T00:00:00Z")

    store.save_belief(b1)
    store.save_belief(b2)

    retriever = KnowledgeRetriever(store)
    past = retriever.query_active_beliefs("org", as_of="2025-06-01T00:00:00Z")
    assert len(past) == 1
    assert past[0].value == "Alice"

    current = retriever.query_active_beliefs("org", as_of="2026-06-01T00:00:00Z")
    assert len(current) == 1
    assert current[0].value == "Bob"
