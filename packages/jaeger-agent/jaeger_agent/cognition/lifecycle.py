"""The one deterministic state machine durable cognition runs on.

Commitments (durable intentions) and runs (attempts to discharge them)
share a vocabulary and a transition table. They share it *literally* —
this module — so the two can never drift into disagreeing about what
"active" is allowed to become.

The rule this file exists to enforce:

    A model may propose a transition. It never decides one.

Every transition is checked here against a fixed table. There is no
callback, no policy hook, and no "the planner said it was done" escape
hatch: if the table forbids the move, the move raises. That is what
makes a crashed run recoverable — the state on disk was written by
this table, not by a sentence a provider generated.
"""

from __future__ import annotations

from datetime import datetime, timezone


STATES = (
    "created",
    "active",
    "waiting_for_user",
    "waiting_for_event",
    "blocked",
    "paused",
    "completed",
    "failed",
    "cancelled",
)

# Reachable from nothing. Once here, the row is history.
TERMINAL = frozenset({"completed", "cancelled"})

# States a run can be lifted out of by ``resume`` — it stopped, but it
# did not finish. ``failed`` is deliberately included: a provider
# outage is not a verdict on the goal.
RESUMABLE = frozenset({
    "waiting_for_user",
    "waiting_for_event",
    "blocked",
    "paused",
    "failed",
})

ALLOWED: dict[str, frozenset[str]] = {
    "created": frozenset({"active", "cancelled"}),
    "active": frozenset({
        "waiting_for_user", "waiting_for_event", "blocked",
        "paused", "completed", "failed", "cancelled",
    }),
    "waiting_for_user": frozenset({"active", "cancelled", "failed"}),
    "waiting_for_event": frozenset({"active", "cancelled", "failed"}),
    "blocked": frozenset({"active", "cancelled", "failed"}),
    "paused": frozenset({"active", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset({"active"}),
    "cancelled": frozenset(),
}


class LifecycleError(RuntimeError):
    """Illegal transition, unknown state, or missing row."""


def now() -> str:
    """UTC, second resolution, sortable. The only clock this layer reads."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_transition(
    ident: str,
    current: str,
    new_state: str,
    *,
    error: type[LifecycleError] = LifecycleError,
) -> None:
    """Raise unless ``current -> new_state`` is in the table.

    ``error`` lets each store raise its own subclass while sharing one
    table, so callers can still catch ``CommitmentError`` specifically.
    Message wording is part of the contract — tests match on it.
    """
    if new_state not in STATES:
        raise error(f"unknown state {new_state!r}")
    if new_state not in ALLOWED.get(current, frozenset()):
        raise error(f"cannot move {ident} from {current} to {new_state}")
