"""Deterministic next-action policy. Not an LLM planner."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jaeger_agent.memory.models import Belief, BeliefStatus


@runtime_checkable
class Planner(Protocol):
    def next_action(
        self,
        *,
        contradicted: bool = False,
        uncertainty: float = 0.0,
        consequence: float = 0.0,
    ) -> str: ...


class EvidenceFirstPlanner:
    """High uncertainty or an open contradiction → gather evidence.

    Consequence without uncertainty may act. These are computational
    dials, not simulated feelings.
    """

    def next_action(
        self,
        *,
        contradicted: bool = False,
        uncertainty: float = 0.0,
        consequence: float = 0.0,
    ) -> str:
        if contradicted:
            return "gather_evidence"
        if consequence >= 0.7 and uncertainty >= 0.5:
            return "gather_evidence"
        if uncertainty >= 0.8:
            return "ask_user"
        return "act"


def uncertainty_from_beliefs(beliefs: list[Belief]) -> float:
    if not beliefs:
        return 1.0
    if any(b.status == BeliefStatus.CONTRADICTED for b in beliefs):
        return 1.0
    active = [b for b in beliefs if b.status == BeliefStatus.ACTIVE]
    if not active:
        return 0.8
    return 1.0 - (sum(b.confidence for b in active) / len(active))


__all__ = ["EvidenceFirstPlanner", "Planner", "uncertainty_from_beliefs"]
