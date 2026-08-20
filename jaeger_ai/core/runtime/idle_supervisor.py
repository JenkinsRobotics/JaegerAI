"""What to do with free time — one decision, every surface.

The TUI already had an idle tick (Deep Think, then the kanban board).
The daemon drained Deep Think and ignored the board. The bridge — the
process ARES keeps alive 24/7 — did neither, and never folded finished
background ``delegate_task`` work back into a turn.

This module is the decision only. Surfaces execute the action: the
bridge emits a synthetic turn, the daemon calls ``run_worker_turn``.
Keeping I/O out of ``decide`` is what makes the order testable without
booting a model.

Priority, highest first:

  1. skip — a turn is already in flight
  2. completion — Hermes-style async-delegation rail; results must not
     wait behind a heartbeat
  3. deep_think — approved coder-model work
  4. board — actionable kanban card
  5. heartbeat — standing checklist, even when the board is empty
  6. idle — nothing to do
"""

from __future__ import annotations

from enum import Enum


class Action(str, Enum):
    SKIP = "skip"
    COMPLETION = "completion"
    DEEP_THINK = "deep_think"
    BOARD = "board"
    HEARTBEAT = "heartbeat"
    IDLE = "idle"


def window_elapsed(idle_seconds: int, *, quiet_for: float) -> bool:
    """True when the idle window has elapsed.

    ``idle_seconds <= 0`` means the window is off — Deep Think / board
    pickup stay manual. Heartbeat has its own interval and does not
    consult this.
    """
    if idle_seconds <= 0:
        return False
    return quiet_for >= idle_seconds


def decide(
    *,
    busy: bool = False,
    has_completions: bool = False,
    idle_ready: bool = False,
    has_deep_think: bool = False,
    has_board: bool = False,
    heartbeat_due: bool = False,
) -> Action:
    """Pick the next autonomous action. Pure: no I/O, no clocks."""
    if busy:
        return Action.SKIP
    if has_completions:
        return Action.COMPLETION
    if idle_ready and has_deep_think:
        return Action.DEEP_THINK
    if idle_ready and has_board:
        return Action.BOARD
    if heartbeat_due:
        return Action.HEARTBEAT
    return Action.IDLE


__all__ = [
    "Action",
    "decide",
    "window_elapsed",
]
