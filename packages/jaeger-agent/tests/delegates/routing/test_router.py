from __future__ import annotations

import asyncio

import pytest

from jaeger_agent.delegates import DelegateRegistry, RuntimeStatus
from jaeger_agent.delegates.health import (
    DelegateObservation,
    InMemoryDelegateHealthStore,
)
from jaeger_agent.delegates.routing import DelegateRouter, NoEligibleDelegate


class Runtime:
    def __init__(self, runtime_id: str, *, local: bool = False) -> None:
        self.runtime_id = runtime_id
        self.local = local

    async def probe(self):
        return RuntimeStatus(
            True,
            capabilities=frozenset({"code"}),
            local=self.local,
        )


def test_router_prefers_observed_effectiveness() -> None:
    registry = DelegateRegistry()
    registry.register(Runtime("alpha"))
    registry.register(Runtime("beta"))
    health = InMemoryDelegateHealthStore()
    for _ in range(4):
        health.record(DelegateObservation("alpha", True, 100, capability="code", quality=0.9))
        health.record(DelegateObservation("beta", False, 100, capability="code", quality=0.2))

    route = asyncio.run(
        DelegateRouter(registry, health).choose(
            required_capabilities=frozenset({"code"})
        )
    )
    assert route.runtime_id == "alpha"


def test_router_enforces_locality_before_ranking() -> None:
    registry = DelegateRegistry()
    registry.register(Runtime("cloud", local=False))
    health = InMemoryDelegateHealthStore()

    with pytest.raises(NoEligibleDelegate):
        asyncio.run(
            DelegateRouter(registry, health).choose(
                required_capabilities=frozenset({"code"}),
                sensitivity="private",
            )
        )
