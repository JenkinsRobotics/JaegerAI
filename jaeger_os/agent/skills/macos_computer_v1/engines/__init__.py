"""Capability-ladder engines for macOS computer control.

Each engine is a self-contained module that knows ONE way to drive
the Mac: AppleScript dispatch, browser CDP, Accessibility object
actions, or the screenshot fallback. The planner picks the first
engine that claims it can handle a given action.

Engine protocol:

  * ``name: str`` — short identifier (``"applescript"``, ``"ax"``,
    ``"browser"``, ``"vision"``).
  * ``priority: int`` — capability-ladder position. Lower = tried
    first. AppleScript is 10, browser 20, AX 30, vision 90.
  * ``is_available() -> (bool, str)`` — runtime preconditions
    (deps installed, OS permissions granted). Reason string is
    the operator's "why is this engine offline?" message.
  * ``can_handle(action: Action) -> Confidence`` — 0.0 ≤ x ≤ 1.0.
    The planner asks every available engine and picks the highest
    confidence above the threshold.
  * ``execute(action: Action) -> EngineResult`` — runs the action;
    returns ``{ok, result, engine, elapsed_ms}`` (success) or
    ``{ok=False, error, engine}`` (failure).

The Action type is intentionally loose — a ``dict[str, Any]`` with
a ``"kind"`` key (open / click / type / read / etc.) plus
per-kind args. Each engine documents which kinds it handles in
``can_handle``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Action:
    """One step in a plan. ``kind`` selects the operation; ``args``
    carries per-kind parameters. Kept dict-like rather than a
    union-of-types because the planner needs to forward unknown
    kinds to whatever engine claims them."""
    kind: str
    args: dict[str, Any]
    target: str = ""  # canonical target hint (app name, URL, element label)


@dataclass(frozen=True)
class EngineResult:
    """One engine's outcome. ``engine`` records which tier ran the
    action so the planner can audit-log the chosen path."""
    ok: bool
    engine: str
    result: Any = None
    error: str = ""
    elapsed_ms: float = 0.0


class Engine(Protocol):
    """Engine surface — every tier implements this."""

    name: str
    priority: int

    def is_available(self) -> tuple[bool, str]:
        """``(True, "")`` when ready; ``(False, reason)`` otherwise."""
        ...

    def can_handle(self, action: Action) -> float:
        """Confidence in [0.0, 1.0] that this engine can perform the
        action. The planner picks the highest non-zero across the
        ladder. Return 0.0 to abstain."""
        ...

    def execute(self, action: Action) -> EngineResult:
        """Run the action. Engines MUST NOT raise — wrap exceptions
        into ``EngineResult(ok=False, error=...)`` so the planner
        can fall through to the next tier."""
        ...


__all__ = ["Action", "Engine", "EngineResult"]
