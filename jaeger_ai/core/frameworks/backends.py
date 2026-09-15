"""The single executable registration table for Jaeger's native backends."""
from __future__ import annotations

from jaeger_ai.contract.frameworks import (
    BackendCapabilities,
    BackendRegistration,
    SOLO_RUNTIMES,
    canonical_runtime,
)

from .hermes_native import hermes_reconcile, hermes_turn
from .native_runs import jaeger_reconcile, jaeger_turn
from .openclaw_native import openclaw_reconcile, openclaw_turn


_NATIVE_CAPABILITIES = BackendCapabilities(
    tools=True,
    conversation_history=True,
    cancellation=True,
    approvals=True,
    reconciliation=True,
)

BACKENDS: dict[str, BackendRegistration] = {
    registration.runtime: registration
    for registration in (
        BackendRegistration("jaeger", jaeger_turn, jaeger_reconcile, _NATIVE_CAPABILITIES),
        BackendRegistration("hermes", hermes_turn, hermes_reconcile, _NATIVE_CAPABILITIES),
        BackendRegistration("openclaw", openclaw_turn, openclaw_reconcile, _NATIVE_CAPABILITIES),
    )
}

if set(BACKENDS) != set(SOLO_RUNTIMES):
    raise RuntimeError("Every solo runtime must have exactly one complete backend registration")


def backend(value: object) -> BackendRegistration:
    """Return the complete registration for any spelling of a solo runtime."""
    runtime = canonical_runtime(value)
    try:
        return BACKENDS[runtime]
    except KeyError:
        raise ValueError(f"{runtime} is an orchestrator, not a solo native backend") from None


__all__ = ["BACKENDS", "backend"]
