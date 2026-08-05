"""Application-neutral contracts between JaegerAgent and an agent runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(slots=True)
class TurnResult:
    """Normalized result of one user turn."""

    text: str = ""
    error: str | None = None


@runtime_checkable
class RuntimeEvents(Protocol):
    """Progress events a runtime can emit without knowing a UI toolkit."""

    def activity(self, kind: str, text: str, *, session: str = "") -> None: ...

    def tool(
        self,
        name: str,
        phase: str,
        *,
        elapsed_s: float = 0.0,
        detail: str = "",
        session: str = "",
    ) -> None: ...


@runtime_checkable
class AgentRuntime(Protocol):
    """Small boundary implemented by an agent engine or application adapter.

    Only :meth:`run_turn` and :meth:`close` are required by the bridge.
    Implementations may additionally provide ``start(events=..., bus=...)``,
    ``steer(text)``, ``context_detail(session)``, and ``health()``; JaegerAgent
    discovers those optional lifecycle hooks without coupling to one engine.
    """

    def run_turn(self, text: str, *, session_key: str) -> TurnResult | Mapping[str, Any] | str: ...

    def close(self) -> None: ...


def normalize_turn_result(value: TurnResult | Mapping[str, Any] | str | None) -> TurnResult:
    """Accept the common return shapes used by existing agent loops."""

    if isinstance(value, TurnResult):
        return value
    if isinstance(value, str):
        return TurnResult(text=value)
    if value is None:
        return TurnResult()
    return TurnResult(
        text=str(value.get("text") or ""),
        error=str(value["error"]) if value.get("error") else None,
    )


__all__ = ["AgentRuntime", "RuntimeEvents", "TurnResult"]

