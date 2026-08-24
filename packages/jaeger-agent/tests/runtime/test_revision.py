"""Belief revision is ranked provenance, never last-write-wins."""

from __future__ import annotations

from jaeger_agent.cognition.revision import revise_group
from jaeger_agent.memory.models import BeliefStatus, Claim, ProvenanceKind


def test_observed_outranks_later_told():
    claims = [
        Claim.create("user", "shell", "bash", ProvenanceKind.OBSERVED),
        Claim.create("user", "shell", "zsh", ProvenanceKind.TOLD),
    ]
    belief = revise_group(claims)
    assert belief is not None
    assert belief.value == "bash"
    assert belief.status == BeliefStatus.ACTIVE


def test_same_rank_conflict_is_contradicted():
    claims = [
        Claim.create("user", "shell", "bash", ProvenanceKind.TOLD),
        Claim.create("user", "shell", "zsh", ProvenanceKind.TOLD),
    ]
    belief = revise_group(claims)
    assert belief is not None
    assert belief.status == BeliefStatus.CONTRADICTED
    assert belief.confidence == 0.0


def test_system_outranks_observation():
    claims = [
        Claim.create("agent", "name", "Jaeger", ProvenanceKind.SYSTEM),
        Claim.create("agent", "name", "Hermes", ProvenanceKind.OBSERVED),
    ]
    belief = revise_group(claims)
    assert belief is not None
    assert belief.value == "Jaeger"
