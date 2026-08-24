"""Durable commitments — unfinished SI intentions that survive restart.

An LLM may propose creating or advancing a commitment. It is not the
authority for whether the work completed: that is this store, with
deterministic transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable
import uuid


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

_ALLOWED: dict[str, frozenset[str]] = {
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

_TERMINAL = frozenset({"completed", "cancelled"})


class CommitmentError(RuntimeError):
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@runtime_checkable
class CommitmentStore(Protocol):
    def create(self, title: str, *, kind: str = "goal",
               payload: dict[str, Any] | None = None) -> Commitment: ...

    def get(self, commitment_id: str) -> Commitment | None: ...

    def list(self, *, state: str | None = None) -> list[Commitment]: ...

    def transition(self, commitment_id: str, new_state: str) -> Commitment: ...


class InMemoryCommitmentStore:
    def __init__(self) -> None:
        self._items: dict[str, Commitment] = {}

    def create(self, title: str, *, kind: str = "goal",
               payload: dict[str, Any] | None = None) -> Commitment:
        now = _now()
        item = Commitment(
            id=uuid.uuid4().hex[:16],
            title=title.strip() or "(untitled)",
            state="created",
            kind=kind,
            payload=dict(payload or {}),
            created_at=now,
            updated_at=now,
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

    def transition(self, commitment_id: str, new_state: str) -> Commitment:
        item = self._items.get(commitment_id)
        if item is None:
            raise CommitmentError(f"no commitment {commitment_id!r}")
        if new_state not in STATES:
            raise CommitmentError(f"unknown state {new_state!r}")
        allowed = _ALLOWED.get(item.state, frozenset())
        if new_state not in allowed:
            raise CommitmentError(
                f"cannot move {item.id} from {item.state} to {new_state}"
            )
        item.state = new_state
        item.updated_at = _now()
        return item
