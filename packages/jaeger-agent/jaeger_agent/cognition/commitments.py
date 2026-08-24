"""Durable commitments — unfinished SI intentions that survive restart.

An LLM may propose creating or advancing a commitment. It is not the
authority for whether the work completed: that is this store, with
deterministic transitions.

A commitment is the *intention* ("migrate the schema"). It is not the
attempt: attempts are runs (``jaeger_agent.cognition.runs``), and one
commitment accumulates many of them across crashes, provider swaps and
restarts. That split is what lets a run fail without the goal being
lost.

Commitments nest. A parent cannot be completed while a child is still
open — checked here, deterministically, because "the subtasks are
basically done" is exactly the judgement a model should not be making.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
import uuid

from jaeger_agent.cognition.lifecycle import (
    ALLOWED as _ALLOWED,
    STATES,
    TERMINAL as _TERMINAL,
    LifecycleError,
    check_transition,
    now as _now,
)


class CommitmentError(LifecycleError):
    """Illegal transition or missing commitment."""


@dataclass(slots=True)
class Commitment:
    id: str
    title: str
    state: str
    kind: str = "goal"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    parent_id: str | None = None


def new_id() -> str:
    return uuid.uuid4().hex[:16]


@runtime_checkable
class CommitmentStore(Protocol):
    def create(self, title: str, *, kind: str = "goal",
               payload: dict[str, Any] | None = None,
               parent_id: str | None = None) -> Commitment: ...

    def get(self, commitment_id: str) -> Commitment | None: ...

    def list(self, *, state: str | None = None) -> list[Commitment]: ...

    def children(self, commitment_id: str) -> list[Commitment]: ...

    def transition(self, commitment_id: str, new_state: str) -> Commitment: ...


def guard_open_children(
    item: Commitment, new_state: str, children: list[Commitment]
) -> None:
    """A parent may not complete while a child is non-terminal.

    Shared by every adapter so the rule cannot hold in memory and lapse
    in SQLite. ``cancelled`` is not guarded: cancelling a parent is a
    decision to abandon the subtree, not a claim the subtree finished.
    """
    if new_state != "completed":
        return
    open_children = [c for c in children if c.state not in _TERMINAL]
    if open_children:
        names = ", ".join(sorted(c.id for c in open_children))
        raise CommitmentError(
            f"cannot complete {item.id} with open children: {names}"
        )


class InMemoryCommitmentStore:
    def __init__(self) -> None:
        self._items: dict[str, Commitment] = {}

    def create(self, title: str, *, kind: str = "goal",
               payload: dict[str, Any] | None = None,
               parent_id: str | None = None) -> Commitment:
        if parent_id is not None and parent_id not in self._items:
            raise CommitmentError(f"no parent commitment {parent_id!r}")
        now = _now()
        item = Commitment(
            id=new_id(),
            title=title.strip() or "(untitled)",
            state="created",
            kind=kind,
            payload=dict(payload or {}),
            created_at=now,
            updated_at=now,
            parent_id=parent_id,
        )
        self._items[item.id] = item
        return item

    def get(self, commitment_id: str) -> Commitment | None:
        return self._items.get(commitment_id)

    def list(self, *, state: str | None = None) -> list[Commitment]:
        rows = list(self._items.values())
        if state is not None:
            rows = [r for r in rows if r.state == state]
        return rows

    def children(self, commitment_id: str) -> list[Commitment]:
        return [r for r in self._items.values() if r.parent_id == commitment_id]

    def transition(self, commitment_id: str, new_state: str) -> Commitment:
        item = self._items.get(commitment_id)
        if item is None:
            raise CommitmentError(f"no commitment {commitment_id!r}")
        check_transition(item.id, item.state, new_state, error=CommitmentError)
        guard_open_children(item, new_state, self.children(commitment_id))
        item.state = new_state
        item.updated_at = _now()
        return item


__all__ = [
    "ALLOWED",
    "STATES",
    "Commitment",
    "CommitmentError",
    "CommitmentStore",
    "InMemoryCommitmentStore",
    "guard_open_children",
    "new_id",
]

# Re-exported for adapters that were written against the private names.
ALLOWED = _ALLOWED
