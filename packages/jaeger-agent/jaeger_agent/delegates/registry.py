"""Thread-safe registry and deterministic eligibility filter for delegates."""

from __future__ import annotations

from threading import RLock

from .contracts import DelegateRuntime, RuntimeStatus


class DelegateRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._runtimes: dict[str, DelegateRuntime] = {}

    def register(self, runtime: DelegateRuntime, *, replace: bool = False) -> None:
        runtime_id = str(getattr(runtime, "runtime_id", "")).strip()
        if not runtime_id:
            raise ValueError("delegate runtime_id must not be empty")
        with self._lock:
            if runtime_id in self._runtimes and not replace:
                raise ValueError(f"delegate runtime already registered: {runtime_id}")
            self._runtimes[runtime_id] = runtime

    def unregister(self, runtime_id: str) -> None:
        with self._lock:
            self._runtimes.pop(runtime_id, None)

    def get(self, runtime_id: str) -> DelegateRuntime | None:
        with self._lock:
            return self._runtimes.get(runtime_id)

    def list(self) -> tuple[DelegateRuntime, ...]:
        with self._lock:
            return tuple(self._runtimes[key] for key in sorted(self._runtimes))

    @staticmethod
    def eligible(
        status: RuntimeStatus,
        *,
        required_capabilities: frozenset[str],
        require_local: bool,
    ) -> bool:
        return (
            status.available
            and (not require_local or status.local)
            and required_capabilities.issubset(status.capabilities)
        )


_REGISTRY = DelegateRegistry()


def get_delegate_registry() -> DelegateRegistry:
    return _REGISTRY
