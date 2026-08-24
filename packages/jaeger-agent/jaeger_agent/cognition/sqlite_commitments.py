"""SQLite adapter for :class:`CommitmentStore`."""

from __future__ import annotations

import json
from typing import Any

from jaeger_agent.cognition.commitments import (
    Commitment,
    CommitmentError,
    InMemoryCommitmentStore,
    STATES,
    _ALLOWED,
    _now,
)
from jaeger_agent.memory import sqlite_store


def _row(row) -> Commitment:
    return Commitment(
        id=str(row["id"]),
        title=str(row["title"]),
        state=str(row["state"]),
        kind=str(row["kind"]),
        payload=json.loads(row["payload_json"] or "{}"),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class SqliteCommitmentStore:
    def create(self, title: str, *, kind: str = "goal",
               payload: dict[str, Any] | None = None) -> Commitment:
        item = InMemoryCommitmentStore().create(title, kind=kind, payload=payload)
        conn = sqlite_store.connection()
        conn.execute(
            "INSERT INTO commitments (id, title, state, kind, payload_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.title, item.state, item.kind,
             json.dumps(item.payload), item.created_at, item.updated_at),
        )
        conn.commit()
        return item

    def get(self, commitment_id: str) -> Commitment | None:
        conn = sqlite_store.connection()
        row = conn.execute(
            "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
        ).fetchone()
        return _row(row) if row else None

    def list(self, *, state: str | None = None) -> list[Commitment]:
        conn = sqlite_store.connection()
        if state is None:
            rows = conn.execute(
                "SELECT * FROM commitments ORDER BY created_at"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM commitments WHERE state = ? ORDER BY created_at",
                (state,),
            ).fetchall()
        return [_row(r) for r in rows]

    def transition(self, commitment_id: str, new_state: str) -> Commitment:
        item = self.get(commitment_id)
        if item is None:
            raise CommitmentError(f"no commitment {commitment_id!r}")
        if new_state not in STATES:
            raise CommitmentError(f"unknown state {new_state!r}")
        if new_state not in _ALLOWED.get(item.state, frozenset()):
            raise CommitmentError(
                f"cannot move {item.id} from {item.state} to {new_state}"
            )
        now = _now()
        conn = sqlite_store.connection()
        conn.execute(
            "UPDATE commitments SET state = ?, updated_at = ? WHERE id = ?",
            (new_state, now, commitment_id),
        )
        conn.commit()
        item.state = new_state
        item.updated_at = now
        return item
