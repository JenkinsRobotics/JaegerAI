"""Active health probes for all registered delegates."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from ..contracts import RuntimeStatus
from ..registry import DelegateRegistry
from .store import DelegateHealthStore, DelegateObservation, get_delegate_health_store


@dataclass(frozen=True, slots=True)
class ProbeResult:
    runtime_id: str
    status: RuntimeStatus
    latency_ms: int


class DelegateHealthService:
    def __init__(
        self,
        registry: DelegateRegistry,
        store: DelegateHealthStore | None = None,
    ) -> None:
        self.registry = registry
        self.store = store or get_delegate_health_store()

    async def check_all(self) -> tuple[ProbeResult, ...]:
        return tuple(await asyncio.gather(*(self._check(item) for item in self.registry.list())))

    async def _check(self, runtime) -> ProbeResult:
        started = time.monotonic()
        status = await runtime.probe()
        latency_ms = round((time.monotonic() - started) * 1000)
        self.store.record(
            DelegateObservation(
                runtime_id=runtime.runtime_id,
                success=status.available,
                latency_ms=latency_ms,
                error_category=None if status.available else "probe_unavailable",
                metadata={"detail": status.detail, "kind": "probe"},
            )
        )
        return ProbeResult(runtime.runtime_id, status, latency_ms)
