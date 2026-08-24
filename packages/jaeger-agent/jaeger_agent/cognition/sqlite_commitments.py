"""SQLite adapter for :class:`CommitmentStore`."""

from __future__ import annotations

import json
from typing import Any

from jaeger_agent.cognition.commitments import (
    Commitment,
    CommitmentError,
    guard_open_children,
    new_id,
)
from jaeger_agent.cognition.lifecycle import check_transition, now as _now
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
        parent_id=row["parent_id"],
    )


class SqliteCommitmentStore:
    def create(self, title: str, *, kind: str = "goal",
               payload: dict[str, Any] | None = None,
               parent_id: str | None = None) -> Commitment:
        if parent_id is not None and self.get(parent_id) is None:
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
        with sqlite_store.writer() as conn:
            conn.execute(
                "INSERT INTO commitments (id, title, state, kind, payload_json, "
                "created_at, updated_at, parent_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item.id, item.title, item.state, item.kind,
                 json.dumps(item.payload), item.created_at, item.updated_at,
                 item.parent_id),
            )
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

    def children(self, commitment_id: str) -> list[Commitment]:
        rows = sqlite_store.connection().execute(
            "SELECT * FROM commitments WHERE parent_id = ? ORDER BY created_at",
            (commitment_id,),
        ).fetchall()
        return [_row(r) for r in rows]

    def transition(self, commitment_id: str, new_state: str) -> Commitment:
        item = self.get(commitment_id)
        if item is None:
            raise CommitmentError(f"no commitment {commitment_id!r}")
        check_transition(item.id, item.state, new_state, error=CommitmentError)
        guard_open_children(item, new_state, self.children(commitment_id))
        now = _now()
        with sqlite_store.writer() as conn:
            conn.execute(
                "UPDATE commitments SET state = ?, updated_at = ? WHERE id = ?",
                (new_state, now, commitment_id),
            )
        item.state = new_state
        item.updated_at = now
        return item
