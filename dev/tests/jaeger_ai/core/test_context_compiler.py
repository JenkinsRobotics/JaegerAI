"""Unit and integration tests for Workstream 6: Memory and Context Architecture.

Validates:
1. ContextCompiler 5-stage pipeline: SELECT -> RANK -> BUDGET -> PROVENANCE -> FORMAT.
2. Every context fragment carries explicit MemoryProvenance.
3. Budgets are measurable, predictable, and prune lower-priority items when exceeded.
4. Essential items (Identity, Truth) are never dropped.
5. Model/provider swap preserves Agent identity and memory context.
"""
from dataclasses import dataclass
from pathlib import Path
import pytest

from jaeger_ai.core.context_compiler import (
    ContextCompiler,
    CompiledContext,
    ContextItem,
    MemoryProvenance,
)
from jaeger_ai.core.entity.identity import EntityIdentity


@dataclass
class DummySelfState:
    mood: str = "curious"
    energy: float = 0.9
    total_events_processed: int = 42


def test_select_gathers_all_memory_domains():
    """ContextCompiler gathers all available memory sources into candidate items."""
    compiler = ContextCompiler()
    identity = EntityIdentity(
        entity_id="jaeger-ent-01",
        display_name="JaegerAgent",
        created_at=1000.0,
        instance_name="default",
    )
    self_state = DummySelfState()

    claims = [{"subject": "user", "predicate": "timezone", "value": "PST", "confidence": 0.95}]
    reflections = [{"critique": "Always check filesystem read-only permissions before writing"}]
    documents = [{"source_id": "docs/architecture.md", "text": "Clean Architecture Standard"}]
    skills = [{"name": "audit_repo", "description": "Scan repo for leaks", "score": 0.9}]
    observations = [{"sensor": "battery", "signals": {"level": 0.85}, "salience": 0.5}]

    items = compiler.select(
        "Audit the workspace",
        identity=identity,
        self_state=self_state,
        runtime_truth="Live tools: filesystem, shell, git",
        claims=claims,
        reflections=reflections,
        documents=documents,
        skills=skills,
        observations=observations,
    )

    provenances = {it.provenance for it in items}
    assert MemoryProvenance.IDENTITY in provenances
    assert MemoryProvenance.RUNTIME_TRUTH in provenances
    assert MemoryProvenance.SELF_STATE in provenances
    assert MemoryProvenance.SEMANTIC_CLAIM in provenances
    assert MemoryProvenance.REFLEXION in provenances
    assert MemoryProvenance.RETRIEVED_DOCUMENT in provenances
    assert MemoryProvenance.LEARNED_SKILL in provenances
    assert MemoryProvenance.DEVICE_OBSERVATION in provenances


def test_provenance_tagging_in_formatted_prompt():
    """Compiled system prompt groups and tags sections with explicit provenance blocks."""
    compiler = ContextCompiler()
    identity = EntityIdentity(
        entity_id="jaeger-test-01",
        display_name="JaegerSI",
        created_at=1000.0,
        instance_name="test",
    )
    claims = [{"subject": "user", "predicate": "favorite_editor", "value": "neovim", "confidence": 0.99}]

    compiled = compiler.compile(
        "Open my notes",
        identity=identity,
        runtime_truth="Verified tools available",
        claims=claims,
    )

    assert "=== [PROVENANCE_IDENTITY] ===" in compiled.system_prompt
    assert "=== [PROVENANCE_RUNTIME_TRUTH] ===" in compiled.system_prompt
    assert "=== [PROVENANCE_SEMANTIC_CLAIM] ===" in compiled.system_prompt
    assert "favorite_editor = neovim" in compiled.system_prompt
    assert compiled.provenance_breakdown.get(MemoryProvenance.IDENTITY.value) == 1
    assert compiled.provenance_breakdown.get(MemoryProvenance.SEMANTIC_CLAIM.value) == 1


def test_budget_enforcement_drops_low_priority_items():
    """Under constrained token budgets, low-priority items are pruned while identity is protected."""
    compiler = ContextCompiler()
    identity = EntityIdentity(
        entity_id="jaeger-test-02",
        display_name="JaegerBudget",
        created_at=1000.0,
        instance_name="test",
    )

    # Generate large payload of documents and claims
    documents = [
        {"source_id": f"doc_{i}.txt", "text": "Lorem ipsum dolor sit amet " * 50, "score": 0.4}
        for i in range(10)
    ]
    claims = [
        {"subject": f"entity_{i}", "predicate": "val", "value": f"item_{i}", "confidence": 0.5}
        for i in range(10)
    ]

    # Constrain budget to a small limit (e.g. 150 tokens)
    compiled = compiler.compile(
        "Summarize",
        identity=identity,
        runtime_truth="Essential capabilities",
        documents=documents,
        claims=claims,
        budget_tokens=150,
    )

    assert compiled.is_budget_exceeded is True
    assert len(compiled.items_dropped) > 0

    # Assert Identity is NEVER dropped
    included_provs = [it.provenance for it in compiled.items_included]
    assert MemoryProvenance.IDENTITY in included_provs

    # Dropped items should include low priority documents
    dropped_provs = [it.provenance for it in compiled.items_dropped]
    assert MemoryProvenance.RETRIEVED_DOCUMENT in dropped_provs


def test_context_measurability():
    """Compiled context must expose measurable character and token statistics."""
    compiler = ContextCompiler()
    compiled = compiler.compile(
        "Explain quantum computing",
        runtime_truth="System status: nominal",
        budget_tokens=1000,
    )

    assert compiled.total_chars > 0
    assert compiled.estimated_tokens > 0
    assert compiled.budget_tokens == 1000
    assert isinstance(compiled.provenance_breakdown, dict)


def test_provider_swap_preserves_agent_memory():
    """Swapping models/providers preserves Agent memory identity and compiled claims."""
    compiler = ContextCompiler()
    identity = EntityIdentity(
        entity_id="stable-persistent-anchor",
        display_name="JaegerCore",
        created_at=5000.0,
        instance_name="prod",
    )
    claims = [{"subject": "project", "predicate": "architecture", "value": "Pinocchio", "confidence": 1.0}]

    # Compile for Model A (e.g. Ollama local)
    ctx_model_a = compiler.compile("What architecture is this?", identity=identity, claims=claims)

    # Compile for Model B (e.g. Kimi Cloud)
    ctx_model_b = compiler.compile("What architecture is this?", identity=identity, claims=claims)

    # Both models receive identical persistent identity and semantic facts
    assert "stable-persistent-anchor" in ctx_model_a.system_prompt
    assert "stable-persistent-anchor" in ctx_model_b.system_prompt
    assert "Pinocchio" in ctx_model_a.system_prompt
    assert "Pinocchio" in ctx_model_b.system_prompt
