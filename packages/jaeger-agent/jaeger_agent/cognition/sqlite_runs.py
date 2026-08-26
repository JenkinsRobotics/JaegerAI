"""SQLite adapters for :class:`RunStore` and :class:`EffectLedger`.

Every mutation goes through ``sqlite_store.writer()`` — the write lock
plus ``BEGIN IMMEDIATE``. That matters more here than elsewhere in the
codebase: checkpoint sequence allocation is a read-then-write, and the
effect claim is the single point that stops an email being sent twice.
Both must be atomic against another process doing the same thing at the
same moment, which is exactly what ``BEGIN IMMEDIATE`` buys.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable

from jaeger_agent.cognition.effects import (
    Effect,
    EffectError,
    EffectIndeterminate,
)
from jaeger_agent.cognition.lifecycle import check_transition, now as _now
from jaeger_agent.cognition.runs import (
    Checkpoint,
    Run,
    RunError,
    check_resumable,
    check_wait,
    new_id,
    pid_is_alive,
)
from jaeger_agent.memory import sqlite_store


def _effect(row: sqlite3.Row) -> Effect:
    raw = row["result_json"]
    return Effect(
        key=str(row["key"]),
        action=str(row["action"]),
        status=str(row["status"]),
        result=json.loads(raw) if raw is not None else None,
        run_id=row["run_id"],
        claimed_at=str(row["claimed_at"]),
        completed_at=row["completed_at"],
    )


def _run(row: sqlite3.Row) -> Run:
    return Run(
        id=str(row["id"]),
        commitment_id=str(row["commitment_id"]),
        state=str(row["state"]),
        attempt=int(row["attempt"]),
        owner_pid=row["owner_pid"],
        heartbeat_at=row["heartbeat_at"],
        wake_key=row["wake_key"],
        provider=row["provider"],
        reason=row["reason"],
        payload=json.loads(row["payload_json"] or "{}"),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        parent_run_id=row["parent_run_id"],
        root_run_id=row["root_run_id"],
        relation=str(row["relation"] or "root"),
    )


def _checkpoint(row: sqlite3.Row) -> Checkpoint:
    return Checkpoint(
        run_id=str(row["run_id"]),
        seq=int(row["seq"]),
        cursor=json.loads(row["cursor_json"] or "{}"),
        created_at=str(row["created_at"]),
    )


class SqliteRunStore:
    def create(self, commitment_id: str, *, provider: str | None = None,
               owner_pid: int | None = None,
               payload: dict[str, Any] | None = None,
               parent_run_id: str | None = None,
               relation: str = "root") -> Run:
        now = _now()
        with sqlite_store.writer() as conn:
            parent_row = conn.execute("SELECT * FROM runs WHERE id = ?", (parent_run_id,)).fetchone() if parent_run_id else None
            if parent_run_id and parent_row is None:
                raise RunError(f"no parent run {parent_run_id!r}")
            if parent_run_id and not str(relation or "").strip():
                raise RunError("child run requires a relation")
            parent = _run(parent_row) if parent_row else None
            attempt = int(conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) + 1 AS n FROM runs "
                "WHERE commitment_id = ?", (commitment_id,),
            ).fetchone()["n"])
            run = Run(
                id=new_id(),
                commitment_id=commitment_id,
                state="created",
                attempt=attempt,
                owner_pid=owner_pid,
                heartbeat_at=now if owner_pid is not None else None,
                provider=provider,
                payload=dict(payload or {}),
                created_at=now,
                updated_at=now,
                parent_run_id=parent_run_id,
                root_run_id=(parent.root_run_id or parent.id) if parent else None,
                relation=str(relation or "root"),
            )
            conn.execute(
                "INSERT INTO runs (id, commitment_id, state, attempt, owner_pid, "
                "heartbeat_at, wake_key, provider, reason, payload_json, "
                "created_at, updated_at, parent_run_id, root_run_id, relation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.id, run.commitment_id, run.state, run.attempt, run.owner_pid,
                 run.heartbeat_at, None, run.provider, None,
                 json.dumps(run.payload), run.created_at, run.updated_at,
                 run.parent_run_id, run.root_run_id, run.relation),
            )
        return run

    def get(self, run_id: str) -> Run | None:
        row = sqlite_store.connection().execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return _run(row) if row else None

    def list(self, *, commitment_id: str | None = None,
             state: str | None = None) -> list[Run]:
        clauses, params = [], []
        if commitment_id is not None:
            clauses.append("commitment_id = ?")
            params.append(commitment_id)
        if state is not None:
            clauses.append("state = ?")
            params.append(state)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = sqlite_store.connection().execute(
            f"SELECT * FROM runs{where} ORDER BY created_at, attempt", params
        ).fetchall()
        return [_run(r) for r in rows]

    def children(self, run_id: str) -> list[Run]:
        self._require(run_id)
        rows = sqlite_store.connection().execute(
            "SELECT * FROM runs WHERE parent_run_id = ? ORDER BY created_at", (run_id,),
        ).fetchall()
        return [_run(row) for row in rows]

    def lineage(self, run_id: str) -> list[Run]:
        run = self._require(run_id)
        root_id = run.root_run_id or run.id
        rows = sqlite_store.connection().execute(
            "SELECT * FROM runs WHERE id = ? OR root_run_id = ? ORDER BY created_at", (root_id, root_id),
        ).fetchall()
        return [_run(row) for row in rows]

    def _require(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run is None:
            raise RunError(f"no run {run_id!r}")
        return run

    def transition(self, run_id: str, new_state: str, *,
                   reason: str | None = None,
                   wake_key: str | None = None) -> Run:
        run = self._require(run_id)
        check_transition(run.id, run.state, new_state, error=RunError)
        check_wait(new_state, wake_key)
        key = wake_key if new_state == "waiting_for_event" else None
        pid = run.owner_pid if new_state == "active" else None
        now = _now()
        with sqlite_store.writer() as conn:
            conn.execute(
                "UPDATE runs SET state = ?, reason = ?, wake_key = ?, "
                "owner_pid = ?, updated_at = ? WHERE id = ?",
                (new_state, reason, key, pid, now, run_id),
            )
        run.state, run.reason, run.wake_key = new_state, reason, key
        run.owner_pid, run.updated_at = pid, now
        return run

    def heartbeat(self, run_id: str, *, owner_pid: int | None = None) -> Run:
        run = self._require(run_id)
        now = _now()
        pid = owner_pid if owner_pid is not None else run.owner_pid
        with sqlite_store.writer() as conn:
            conn.execute(
                "UPDATE runs SET owner_pid = ?, heartbeat_at = ? WHERE id = ?",
                (pid, now, run_id),
            )
        run.owner_pid, run.heartbeat_at = pid, now
        return run

    def checkpoint(self, run_id: str, cursor: dict[str, Any]) -> Checkpoint:
        self._require(run_id)
        now = _now()
        with sqlite_store.writer() as conn:
            # MAX+1 and the INSERT share one BEGIN IMMEDIATE, so two
            # writers cannot both allocate the same seq. The (run_id, seq)
            # primary key is the backstop if that ever stops being true.
            seq = int(conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM checkpoints "
                "WHERE run_id = ?", (run_id,),
            ).fetchone()["n"])
            conn.execute(
                "INSERT INTO checkpoints (run_id, seq, cursor_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (run_id, seq, json.dumps(cursor), now),
            )
        return Checkpoint(run_id, seq, dict(cursor), now)

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        self._require(run_id)
        row = sqlite_store.connection().execute(
            "SELECT * FROM checkpoints WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return _checkpoint(row) if row else None

    def resume(self, run_id: str, *, provider: str | None = None,
               owner_pid: int | None = None) -> tuple[Run, Checkpoint | None]:
        run = self._require(run_id)
        check_resumable(run)
        now = _now()
        new_provider = provider if provider is not None else run.provider
        with sqlite_store.writer() as conn:
            conn.execute(
                "UPDATE runs SET state = 'active', wake_key = NULL, reason = NULL, "
                "provider = ?, owner_pid = ?, heartbeat_at = ?, updated_at = ? "
                "WHERE id = ?",
                (new_provider, owner_pid, now, now, run_id),
            )
        run.state, run.wake_key, run.reason = "active", None, None
        run.provider, run.owner_pid = new_provider, owner_pid
        run.heartbeat_at = run.updated_at = now
        return run, self.latest_checkpoint(run_id)

    def recover(self, *,
                is_alive: Callable[[int], bool] = pid_is_alive) -> list[Run]:
        orphans = [
            r for r in self.list(state="active")
            if r.owner_pid is not None and not is_alive(r.owner_pid)
        ]
        return [
            self.transition(r.id, "blocked", reason="owner_lost")
            for r in orphans
        ]

    def deliver_event(self, wake_key: str) -> list[Run]:
        now = _now()
        with sqlite_store.writer() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE state = 'waiting_for_event' "
                "AND wake_key = ? ORDER BY created_at", (wake_key,),
            ).fetchall()
            if not rows:
                return []
            conn.execute(
                "UPDATE runs SET state = 'active', wake_key = NULL, reason = NULL, "
                "updated_at = ? WHERE state = 'waiting_for_event' AND wake_key = ?",
                (now, wake_key),
            )
        woken = []
        for row in rows:
            run = _run(row)
            run.state, run.wake_key, run.reason = "active", None, None
            run.updated_at = now
            woken.append(run)
        return woken


class SqliteEffectLedger:
    """At-most-once side effects, durable across process death.

    The claim INSERT is what makes this work: a second process claiming
    a live key hits the primary key and is told the effect is already
    spoken for, rather than sending a second email and finding out later.
    """

    def once(self, key: str, action: str, fn: Callable[[], Any], *,
             run_id: str | None = None) -> tuple[Any, bool]:
        existing = self.get(key)
        if existing is not None:
            if existing.status == "done":
                return existing.result, False
            raise EffectIndeterminate(key, existing.claimed_at)

        claimed_at = _now()
        try:
            with sqlite_store.writer() as conn:
                conn.execute(
                    "INSERT INTO effects (key, action, status, result_json, "
                    "run_id, claimed_at, completed_at) "
                    "VALUES (?, ?, 'pending', NULL, ?, ?, NULL)",
                    (key, action, run_id, claimed_at),
                )
        except sqlite3.IntegrityError:
            # Another process claimed it between the read and the write.
            # Whatever it is doing, this process must not also do it.
            current = self.get(key)
            if current is not None and current.status == "done":
                return current.result, False
            raise EffectIndeterminate(
                key, current.claimed_at if current else claimed_at
            ) from None

        # A crash anywhere in here leaves the row 'pending' deliberately:
        # the next process must not assume either outcome.
        result = fn()
        return self.resolve(key, result).result, True

    def get(self, key: str) -> Effect | None:
        row = sqlite_store.connection().execute(
            "SELECT * FROM effects WHERE key = ?", (key,)
        ).fetchone()
        return _effect(row) if row else None

    def list(self, *, status: str | None = None) -> list[Effect]:
        clauses, params = [], []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = sqlite_store.connection().execute(
            f"SELECT * FROM effects{where} ORDER BY claimed_at", params
        ).fetchall()
        return [_effect(r) for r in rows]

    def resolve(self, key: str, result: Any = None) -> Effect:
        """Settle a pending claim. The UPDATE is conditional on
        ``status = 'pending'`` so a concurrent abandon cannot race a
        completed side effect back into the unclaimed pool, and a
        concurrent resolve cannot overwrite a recorded result."""
        completed_at = _now()
        encoded = json.dumps(result)
        with sqlite_store.writer() as conn:
            updated = conn.execute(
                "UPDATE effects SET status = 'done', result_json = ?, "
                "completed_at = ? WHERE key = ? AND status = 'pending'",
                (encoded, completed_at, key),
            ).rowcount
            row = conn.execute(
                "SELECT * FROM effects WHERE key = ?", (key,)
            ).fetchone()
        if updated == 1:
            return _effect(row)
        if row is None:
            raise EffectError(f"no effect {key!r}")
        raise EffectError(f"effect {key!r} is already done")

    def abandon(self, key: str) -> None:
        """Free a pending claim. DELETE is conditional on pending so a
        stale reader that saw pending cannot delete a row another
        process has already resolved."""
        with sqlite_store.writer() as conn:
            deleted = conn.execute(
                "DELETE FROM effects WHERE key = ? AND status = 'pending'",
                (key,),
            ).rowcount
            if deleted == 1:
                return
            row = conn.execute(
                "SELECT status FROM effects WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            raise EffectError(f"no effect {key!r}")
        raise EffectError(f"effect {key!r} is already done")


__all__ = ["SqliteEffectLedger", "SqliteRunStore"]
