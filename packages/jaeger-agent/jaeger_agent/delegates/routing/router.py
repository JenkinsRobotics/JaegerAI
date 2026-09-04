"""Deterministic routing across available, policy-eligible delegates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..health import DelegateHealthStore, Effectiveness, get_delegate_health_store
from ..registry import DelegateRegistry


class NoEligibleDelegate(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelegateRoute:
    runtime_id: str
    score: float
    effectiveness: Effectiveness
    reason: str


class DelegateRouter:
    def __init__(
        self,
        registry: DelegateRegistry,
        health: DelegateHealthStore | None = None,
    ) -> None:
        self.registry = registry
        self.health = health or get_delegate_health_store()

    async def rank(
        self,
        *,
        required_capabilities: frozenset[str] = frozenset(),
        sensitivity: str = "personal",
        preferred: str | None = None,
    ) -> tuple[DelegateRoute, ...]:
        """Every eligible delegate, best first.

        The full order is what makes failover possible: a caller that only
        gets the winner has nowhere to go when that delegate is available at
        probe time and then fails mid-run, which is the common case (a CLI
        that is installed but unauthenticated, a rate limit, a crash).
        Ties break on runtime_id so the order is deterministic.
        """
        require_local = sensitivity in {"private", "secret"}
        runtimes = self.registry.list()
        statuses = await asyncio.gather(*(runtime.probe() for runtime in runtimes))
        capability = min(required_capabilities) if required_capabilities else "general"
        candidates: list[DelegateRoute] = []
        for runtime, status in zip(runtimes, statuses, strict=True):
            if not self.registry.eligible(
                status,
                required_capabilities=required_capabilities,
                require_local=require_local,
            ):
                continue
            effectiveness = self.health.effectiveness(runtime.runtime_id, capability)
            score = _score(effectiveness, preferred == runtime.runtime_id)
            candidates.append(
                DelegateRoute(
                    runtime.runtime_id,
                    score,
                    effectiveness,
                    "eligible; ranked by success, quality, latency, cost, and preference",
                )
            )
        return tuple(sorted(candidates, key=lambda item: (-item.score, item.runtime_id)))

    async def choose(
        self,
        *,
        required_capabilities: frozenset[str] = frozenset(),
        sensitivity: str = "personal",
        preferred: str | None = None,
    ) -> DelegateRoute:
        routes = await self.rank(
            required_capabilities=required_capabilities,
            sensitivity=sensitivity,
            preferred=preferred,
        )
        if not routes:
            raise NoEligibleDelegate(
                "no available delegate satisfies locality and capability requirements"
            )
        return routes[0]


def _score(effectiveness: Effectiveness, preferred: bool) -> float:
    latency_penalty = min(effectiveness.mean_latency_ms / 120_000, 1.0)
    mean_cost = (
        effectiveness.total_cost_usd / effectiveness.samples
        if effectiveness.samples
        else 0.0
    )
    cost_penalty = min(mean_cost / 5.0, 1.0)
    preference_bonus = 0.05 if preferred else 0.0
    return round(
        0.60 * effectiveness.success_rate
        + 0.25 * effectiveness.mean_quality
        + 0.10 * (1.0 - latency_penalty)
        + 0.05 * (1.0 - cost_penalty)
        + preference_bonus,
        6,
    )
