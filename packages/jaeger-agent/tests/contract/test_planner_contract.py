"""Shared Planner contract — next action is deterministic, not an LLM."""

from __future__ import annotations

import pytest

from jaeger_agent.cognition.planner import EvidenceFirstPlanner, Planner
from jaeger_agent.memory.models import Belief, BeliefStatus


@pytest.fixture
def planner() -> Planner:
    return EvidenceFirstPlanner()


def test_planner_satisfies_protocol(planner):
    assert isinstance(planner, Planner)


def test_contradiction_gathers_evidence(planner):
    assert planner.next_action(contradicted=True) == "gather_evidence"


def test_high_consequence_and_uncertainty_gathers_evidence(planner):
    assert planner.next_action(uncertainty=0.6, consequence=0.9) == "gather_evidence"


def test_low_uncertainty_acts(planner):
    assert planner.next_action(uncertainty=0.1, consequence=0.2) == "act"


def test_uncertainty_from_contradicted_beliefs():
    from jaeger_agent.cognition.planner import uncertainty_from_beliefs

    belief = Belief.create("user", "shell", "bash|zsh", status=BeliefStatus.CONTRADICTED)
    assert uncertainty_from_beliefs([belief]) == 1.0
