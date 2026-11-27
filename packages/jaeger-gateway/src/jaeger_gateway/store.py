"""Standalone WAL SQLite Gateway store for sessions, transcripts, idempotent requests, approvals
& scheduled jobs (one-shot plus durable fixed-delay recurrence)."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping


from jaeger_authority import redact_object, redact_text

MAIN_CHAT_SESSION_ID = "sess_jaeger_chat"

# Bounds for inbound external-channel identifiers and payloads. Anything
# outside these bounds is rejected before any write is attempted.
_CHANNEL_ID_MAX = 128
_EXTERNAL_ID_MAX = 256
_SENDER_MAX = 256
_CHANNEL_BODY_MAX = 20_000


def _is_complete_result(result: Mapping[str, Any] | None) -> bool:
    """True only for an unambiguous ``complete`` verdict.

    Failed, interrupted, E-Stop and uncertain (missing/other verdict) runs are
    never treated as complete, so they never spawn a recurrence successor.
    """
    if not result or result.get("verdict") != "complete":
        return False
    return not any(bool(result.get(flag)) for flag in ("estop", "estop_active", "interrupted", "uncertain"))


def _result_json_is_complete(result_json: Any) -> bool:
    """Canonical completion predicate over a persisted ``result_json`` payload.

    Parses the stored JSON and delegates to :func:`_is_complete_result` only
    when the payload is a JSON object; malformed or non-object payloads are
    never complete. Registered as a deterministic SQLite function so SQL
    claim queries and Python readiness checks cannot disagree.
    """
    try:
        parsed = json.loads(result_json) if isinstance(result_json, str) else None
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, Mapping):
        return False
    return _is_complete_result(parsed)


class RequestConflictError(ValueError):
    """Raised when an existing request_id is replayed with a different input fingerprint."""


class GatewayStore:
    """Durable WAL SQLite catalog for standalone Jaeger Gateway instances."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.create_function(
            "result_json_is_complete", 1, _result_json_is_complete, deterministic=True
        )
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    workspace TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'idle',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    decision TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    job_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    due_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    run_id TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    claimed_at REAL,
                    completed_at REAL,
                    series_id TEXT,
                    interval_s REAL,
                    predecessor_job_id TEXT,
                    fire_seq INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_due
                    ON scheduled_jobs(status, due_at);
                CREATE TABLE IF NOT EXISTS series_controls (
                    series_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (series_id, session_id)
                );
                CREATE TABLE IF NOT EXISTS job_dependencies (
                    child_job_id TEXT NOT NULL,
                    parent_job_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (child_job_id, parent_job_id),
                    FOREIGN KEY(child_job_id) REFERENCES scheduled_jobs(job_id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_job_id) REFERENCES scheduled_jobs(job_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_job_dependencies_parent
                    ON job_dependencies(parent_job_id);
                CREATE TABLE IF NOT EXISTS external_channel_threads (
                    channel TEXT NOT NULL,
                    external_thread_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (channel, external_thread_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS external_channel_messages (
                    channel TEXT NOT NULL,
                    external_thread_id TEXT NOT NULL,
                    external_message_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    message_row_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    content_digest TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (channel, external_thread_id, external_message_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                    FOREIGN KEY(message_row_id) REFERENCES messages(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_external_channel_messages_session
                    ON external_channel_messages(session_id, message_row_id);
                """
            )
            # Backward-compatible migration: databases created before recurrence
            # support get the new columns added in place; fresh databases already
            # have them from the CREATE TABLE above. Existing rows keep working
            # as one-shot jobs (series_id NULL).
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(scheduled_jobs)")}
            for col_name, col_decl in (
                ("series_id", "TEXT"),
                ("interval_s", "REAL"),
                ("predecessor_job_id", "TEXT"),
                ("fire_seq", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE scheduled_jobs ADD COLUMN {col_name} {col_decl}")
            # Created after all ALTER TABLE additions: on pre-existing databases
            # the columns do not exist until the migration above runs, so a
            # CREATE INDEX inside the executescript would fail with
            # "no such column: series_id" before any ALTER TABLE executes.
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduled_jobs_series_predecessor
                    ON scheduled_jobs(series_id, predecessor_job_id)
                    WHERE series_id IS NOT NULL AND predecessor_job_id IS NOT NULL
                """
            )

    def create_scheduled_job(
        self,
        *,
        session_id: str,
        prompt: str,
        due_at: float,
        job_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        recurrence: Mapping[str, Any] | None = None,
        depends_on: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Durably register an owner-created scheduled agent job.

        Without ``recurrence`` this is a plain one-shot job (unchanged behavior).
        With ``recurrence={"interval_s": <positive finite seconds>, "series_id":
        <optional stable id>}`` the job becomes the first fire of a durable
        fixed-delay series: each fire that completes with verdict ``complete``
        schedules exactly one pending successor at completion + interval_s under
        the same stable series ID.

        ``depends_on`` optionally lists parent job IDs for a NEW one-shot job.
        Every parent must already exist, be a one-shot job (no series) in the
        same session, and differ from the new child ID; the child row and its
        dependency links are inserted in one transaction. Because edges can
        only reference pre-existing jobs, cycles are impossible by
        construction. The child is not claimable until every parent is done
        with a persisted ``complete`` verdict.
        """
        jid = job_id or f"job_{uuid.uuid4().hex[:12]}"
        now = time.time()
        series_id: str | None = None
        interval_s: float | None = None
        meta = dict(metadata or {})
        if recurrence is not None:
            try:
                rec = dict(recurrence)
            except (TypeError, ValueError):
                raise ValueError("recurrence must be a mapping with a positive finite interval_s") from None
            raw_interval = rec.get("interval_s")
            if isinstance(raw_interval, bool) or not isinstance(raw_interval, (int, float)):
                raise ValueError("recurrence.interval_s must be a positive finite number of seconds")
            interval = float(raw_interval)
            if not math.isfinite(interval) or interval <= 0:
                raise ValueError("recurrence.interval_s must be a positive finite number of seconds")
            series_id = str(rec.get("series_id") or f"series_{uuid.uuid4().hex[:12]}")
            interval_s = interval
            meta = {
                **meta,
                "series_id": series_id,
                "interval_s": interval_s,
                "fire_seq": 0,
                "recurrence": {"kind": "fixed_delay", "interval_s": interval_s},
            }
        parent_ids: list[str] = []
        if depends_on is not None:
            if series_id is not None:
                raise ValueError("depends_on is only supported for one-shot jobs (no recurrence)")
            seen: set[str] = set()
            for raw in depends_on:
                pid = str(raw)
                if pid == jid:
                    raise ValueError("a job cannot depend on itself")
                if pid in seen:
                    continue
                seen.add(pid)
                parent_ids.append(pid)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._insert_pending_job(
                    conn, jid, session_id, prompt, float(due_at), meta, now, series_id, interval_s,
                )
                for pid in parent_ids:
                    parent = conn.execute(
                        """SELECT job_id, session_id, series_id FROM scheduled_jobs
                           WHERE job_id = ?""",
                        (pid,),
                    ).fetchone()
                    if parent is None:
                        raise ValueError(f"unknown parent job: {pid!r}")
                    if parent["session_id"] != session_id:
                        raise ValueError(f"parent job {pid!r} belongs to another session")
                    if parent["series_id"] is not None:
                        raise ValueError(f"parent job {pid!r} is a recurrence fire, not a one-shot job")
                    conn.execute(
                        """INSERT INTO job_dependencies(child_job_id, parent_job_id, session_id, created_at)
                           VALUES (?, ?, ?, ?)""",
                        (jid, pid, session_id, now),
                    )
                if parent_ids:
                    meta["depends_on"] = list(parent_ids)
                    conn.execute(
                        "UPDATE scheduled_jobs SET metadata_json = ? WHERE job_id = ?",
                        (json.dumps(meta, default=str), jid),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_scheduled_job(jid) or {}

    def get_scheduled_job(self, job_id: str) -> dict[str, Any] | None:
        """Read back a scheduled job (and its run result) by stable job ID."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row is not None else None

    def cancel_pending_job(self, job_id: str, session_id: str) -> dict[str, Any] | None:
        """Atomically cancel a PENDING one-shot job owned by ``session_id``.

        Uses BEGIN IMMEDIATE so the cancel races safely against claim_due_job:
        exactly one of the two transactions wins the row. The UPDATE only fires
        when the session matches, the job is one-shot (series_id IS NULL) and
        the status is still 'pending' — claimed/running and terminal jobs are
        never altered. Returns the cancelled row on success, or a distinct
        outcome dict: {"error": "not_found"} when no such job exists in this
        session, {"error": "cannot_cancel"} when the job exists but is not a
        pending one-shot. No rows are ever deleted. Cancelling uses the existing
        'cancelled' status, so dependent children become blocked and can never
        dispatch.
        """
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
                if row is None or row["session_id"] != session_id:
                    conn.rollback()
                    return {"error": "not_found"}
                if row["series_id"] is not None or row["status"] != "pending":
                    conn.rollback()
                    return {"error": "cannot_cancel"}
                conn.execute(
                    """UPDATE scheduled_jobs
                       SET status = 'cancelled', completed_at = ?
                       WHERE job_id = ? AND session_id = ? AND series_id IS NULL
                         AND status = 'pending'""",
                    (now, job_id, session_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            cancelled = conn.execute(
                "SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(cancelled) if cancelled is not None else {"error": "not_found"}

    def list_scheduled_jobs(
        self, session_id: str | None = None, *, status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List scheduled jobs (optionally filtered by session and/or status), oldest first."""
        with self._lock, self._connect() as conn:
            clauses: list[str] = []
            params: list[str] = []
            if session_id is not None:
                clauses.append("session_id = ?")
                params.append(session_id)
            if status is not None:
                clauses.append("status = ?")
                params.append(status)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM scheduled_jobs{where} ORDER BY due_at, created_at, job_id",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def list_series_jobs(self, series_id: str) -> list[dict[str, Any]]:
        """List every fire of a recurrence series by stable series ID, oldest first."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM scheduled_jobs WHERE series_id = ?
                   ORDER BY fire_seq, created_at, job_id""",
                (series_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    _SERIES_STATUSES = ("active", "paused", "cancelled")

    def set_series_status(self, series_id: str, session_id: str, status: str) -> dict[str, Any]:
        """Persist a series control state (active/paused/cancelled), serialized
        with claims and settlements via BEGIN IMMEDIATE.

        Rejects unknown statuses and unknown series (no fires for that
        series+session). A cancelled series can never be reactivated or paused
        again. Cancelling also marks all existing pending fires of the series
        cancelled in the same transaction; in-flight (claimed) fires are left
        untouched so their recorded result stays truthful — cancel only governs
        future scheduling (no successor will be spawned). Pause/resume leave the
        pending successor and its fixed due time untouched.
        """
        if status not in self._SERIES_STATUSES:
            raise ValueError(f"invalid series status: {status!r}")
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                exists = conn.execute(
                    "SELECT 1 FROM scheduled_jobs WHERE series_id = ? AND session_id = ? LIMIT 1",
                    (series_id, session_id),
                ).fetchone()
                if exists is None:
                    conn.rollback()
                    raise ValueError(f"unknown series: {series_id!r} for session {session_id!r}")
                current = conn.execute(
                    "SELECT status FROM series_controls WHERE series_id = ? AND session_id = ?",
                    (series_id, session_id),
                ).fetchone()
                if current is not None and current["status"] == "cancelled":
                    conn.rollback()
                    raise ValueError(f"series {series_id!r} is cancelled and cannot be changed")
                conn.execute(
                    """INSERT INTO series_controls(series_id, session_id, status, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(series_id, session_id)
                       DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at""",
                    (series_id, session_id, status, now),
                )
                if status == "cancelled":
                    conn.execute(
                        """UPDATE scheduled_jobs SET status = 'cancelled', completed_at = ?
                           WHERE series_id = ? AND session_id = ? AND status = 'pending'""",
                        (now, series_id, session_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_series_status(series_id, session_id) or {}

    def get_series_status(self, series_id: str, session_id: str) -> dict[str, Any] | None:
        """Read the effective control state of a series for a session.

        Series created before the controls table existed (or with no explicit
        row) default to 'active'. Returns None for unknown series.
        """
        with self._lock, self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM scheduled_jobs WHERE series_id = ? AND session_id = ? LIMIT 1",
                (series_id, session_id),
            ).fetchone()
            if exists is None:
                return None
            row = conn.execute(
                "SELECT status, updated_at FROM series_controls WHERE series_id = ? AND session_id = ?",
                (series_id, session_id),
            ).fetchone()
        if row is None:
            return {"series_id": series_id, "session_id": session_id, "status": "active", "updated_at": None}
        return {
            "series_id": series_id,
            "session_id": session_id,
            "status": row["status"],
            "updated_at": row["updated_at"],
        }

    def claim_due_job(self, *, now: float | None = None) -> dict[str, Any] | None:
        """Atomically claim the oldest due pending job.

        Uses BEGIN IMMEDIATE so two competing claimers cannot both win:
        exactly one UPDATE ... WHERE status='pending' succeeds. Pending fires of
        paused or cancelled series are skipped (one-shot jobs have no series and
        are never skipped). A pending job with unmet dependencies is skipped too:
        it becomes claimable only once every parent job is done with a persisted
        ``complete`` verdict (no estop/interrupted/uncertain flags), so a
        failed, cancelled or interrupted parent blocks the child durably across
        restarts. Returns the claimed row (with a fresh run_id), or None if
        nothing is due and ready.
        """
        now = time.time() if now is None else float(now)
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """SELECT job_id FROM scheduled_jobs j
                       WHERE j.status = 'pending' AND j.due_at <= ?
                         AND NOT EXISTS (
                             SELECT 1 FROM series_controls c
                             WHERE c.series_id = j.series_id
                               AND c.session_id = j.session_id
                               AND c.status IN ('paused', 'cancelled')
                         )
                         AND NOT EXISTS (
                             SELECT 1 FROM job_dependencies d
                             JOIN scheduled_jobs p ON p.job_id = d.parent_job_id
                             WHERE d.child_job_id = j.job_id
                               AND (p.status != 'done'
                                    OR NOT result_json_is_complete(p.result_json))
                         )
                       ORDER BY j.due_at, j.created_at LIMIT 1""",
                    (now,),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                cur = conn.execute(
                    """UPDATE scheduled_jobs
                       SET status = 'claimed', claimed_at = ?, run_id = ?
                       WHERE job_id = ? AND status = 'pending'""",
                    (now, run_id, row["job_id"]),
                )
                if cur.rowcount != 1:
                    conn.rollback()
                    return None
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            claimed = conn.execute(
                "SELECT * FROM scheduled_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
        return dict(claimed) if claimed is not None else None

    def get_job_dependencies(self, job_id: str, session_id: str) -> dict[str, Any] | None:
        """Return the parent links of a job plus its dependency readiness.

        ``parents`` lists each parent's job_id, session_id, status and verdict
        (None when no verdict is persisted). ``readiness`` is ``ready`` when
        every parent is done with an unambiguous ``complete`` verdict, ``blocked``
        when at least one parent reached a terminal non-complete state (failed,
        cancelled, interrupted, or done without a complete verdict), and
        ``waiting`` while parents are still pending/claimed. Returns None for an
        unknown job or a job belonging to another session.
        """
        with self._lock, self._connect() as conn:
            job = conn.execute(
                "SELECT job_id, session_id FROM scheduled_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if job is None or job["session_id"] != session_id:
                return None
            rows = conn.execute(
                """SELECT p.job_id, p.session_id, p.status, p.result_json
                   FROM job_dependencies d
                   JOIN scheduled_jobs p ON p.job_id = d.parent_job_id
                   WHERE d.child_job_id = ?
                   ORDER BY p.created_at, p.job_id""",
                (job_id,),
            ).fetchall()
        parents: list[dict[str, Any]] = []
        saw_blocking_terminal = False
        saw_unfinished = False
        for row in rows:
            try:
                result = json.loads(row["result_json"] or "{}")
            except (TypeError, ValueError):
                result = {}
            if not isinstance(result, Mapping):
                result = {}
            verdict = result.get("verdict")
            complete = row["status"] == "done" and _is_complete_result(result)
            if complete:
                pass
            elif row["status"] in ("failed", "cancelled", "interrupted"):
                saw_blocking_terminal = True
            elif row["status"] == "done":
                # done without an unambiguous complete verdict: terminal block
                saw_blocking_terminal = True
            else:
                saw_unfinished = True
            parents.append({
                "job_id": row["job_id"],
                "session_id": row["session_id"],
                "status": row["status"],
                "verdict": verdict,
            })
        if not parents:
            readiness = "ready"
        elif saw_blocking_terminal:
            readiness = "blocked"
        elif saw_unfinished:
            readiness = "waiting"
        else:
            readiness = "ready"
        return {
            "job_id": job_id,
            "session_id": session_id,
            "parents": parents,
            "readiness": readiness,
        }

    def _spawn_successor_locked(
        self,
        conn: sqlite3.Connection,
        job_row: sqlite3.Row | Mapping[str, Any],
        *,
        completed_at: float,
    ) -> dict[str, Any] | None:
        """Insert exactly one pending successor fire for a completed recurring fire.

        Must be called inside the caller's open write transaction so the settle
        and the successor insert commit or roll back together. Idempotent: a
        successor for this predecessor is never inserted twice (guarded by a
        SELECT plus the partial unique index on (series_id, predecessor_job_id)).
        Returns the successor row, or None for one-shot fires, unusable
        intervals, or when a successor already exists.
        """
        series_id = job_row["series_id"]
        interval_raw = job_row["interval_s"]
        if not series_id or interval_raw is None:
            return None
        try:
            interval_s = float(interval_raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(interval_s) or interval_s <= 0:
            return None
        # A cancelled series never spawns successors, including from a fire that
        # was already in flight when the cancel landed. A paused series still
        # spawns: the successor simply stays pending (fixed due time preserved)
        # until the series is resumed.
        control = conn.execute(
            """SELECT status FROM series_controls
               WHERE series_id = ? AND session_id = ?""",
            (series_id, job_row["session_id"]),
        ).fetchone()
        if control is not None and control["status"] == "cancelled":
            return None
        predecessor_job_id = job_row["job_id"]
        existing = conn.execute(
            """SELECT * FROM scheduled_jobs
               WHERE series_id = ? AND predecessor_job_id = ?""",
            (series_id, predecessor_job_id),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        fire_seq = int(job_row["fire_seq"] or 0) + 1
        successor_id = f"job_{uuid.uuid4().hex[:12]}"
        metadata = json.loads(job_row["metadata_json"] or "{}")
        metadata = {
            **metadata,
            "series_id": series_id,
            "interval_s": interval_s,
            "predecessor_job_id": predecessor_job_id,
            "fire_seq": fire_seq,
            "recurrence": {"kind": "fixed_delay", "interval_s": interval_s},
        }
        conn.execute(
            """INSERT INTO scheduled_jobs(job_id, session_id, prompt, due_at, status,
                                           result_json, metadata_json, created_at,
                                           series_id, interval_s, predecessor_job_id, fire_seq)
               VALUES (?, ?, ?, ?, 'pending', '{}', ?, ?, ?, ?, ?, ?)""",
            (
                successor_id,
                job_row["session_id"],
                job_row["prompt"],
                float(completed_at) + interval_s,
                json.dumps(metadata, default=str),
                float(completed_at),
                series_id,
                interval_s,
                predecessor_job_id,
                fire_seq,
            ),
        )
        row = conn.execute(
            "SELECT * FROM scheduled_jobs WHERE job_id = ?", (successor_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def settle_scheduled_job(
        self,
        job_id: str,
        *,
        status: str,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Record the final result of a claimed job (done/failed/cancelled).

        Settling a known claimed recurring fire as ``done`` with an unambiguous
        ``complete`` verdict inserts exactly one pending successor fire at
        completion + interval in the same SQLite transaction. Failed, cancelled,
        interrupted, E-Stop or uncertain outcomes never spawn a successor, and a
        completed fire record is never modified again (stable job/run IDs).
        """
        if status not in ("done", "failed", "cancelled"):
            raise ValueError(f"invalid scheduled job status: {status!r}")
        now = time.time()
        result_payload = dict(result or {})
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    """UPDATE scheduled_jobs
                       SET status = ?, result_json = ?, completed_at = ?
                       WHERE job_id = ? AND status = 'claimed'""",
                    (status, json.dumps(result_payload), now, job_id),
                )
                if cur.rowcount == 1 and status == "done" and _is_complete_result(result_payload):
                    row = conn.execute(
                        "SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,)
                    ).fetchone()
                    if row is not None:
                        self._spawn_successor_locked(conn, row, completed_at=now)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_scheduled_job(job_id)

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        """Read back a request row (status + result) by stable request ID."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
        if row is None:
            return None
        return {
            "request_id": row["request_id"],
            "session_id": row["session_id"],
            "status": row["status"],
            "result": json.loads(row["result_json"] or "{}"),
        }

    def reconcile_claimed_jobs(self) -> list[str]:
        """Boot-time reconciliation of jobs stuck in 'claimed' after a crash.

        Known terminal request outcomes are copied onto the job; unresolved or
        missing outcomes become 'interrupted' for owner review. No tools are
        replayed. A recovered known-complete recurring fire spawns exactly one
        pending successor in the same transaction; repeating recovery never
        duplicates a fire. Returns the job IDs that were reconciled.
        """
        now = time.time()
        reconciled: list[str] = []
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    "SELECT job_id, run_id FROM scheduled_jobs WHERE status = 'claimed'"
                ).fetchall()
                for row in rows:
                    job_id, run_id = row["job_id"], row["run_id"]
                    req = None
                    if run_id:
                        req_row = conn.execute(
                            "SELECT status, result_json, updated_at FROM requests WHERE request_id = ?", (run_id,)
                        ).fetchone()
                        if req_row is not None:
                            req = {
                                "status": req_row["status"],
                                "result": json.loads(req_row["result_json"] or "{}"),
                                "updated_at": req_row["updated_at"],
                            }
                    if req is not None and req["status"] in ("completed", "failed"):
                        # 'done' requires BOTH a completed storage status AND a complete
                        # verdict; a completed-but-budget_exhausted request is failed.
                        done = req["status"] == "completed" and req.get("result", {}).get("verdict") == "complete"
                        status = "done" if done else "failed"
                        conn.execute(
                            """UPDATE scheduled_jobs SET status = ?, result_json = ?, completed_at = ?
                               WHERE job_id = ? AND status = 'claimed'""",
                            (status, json.dumps(req["result"], default=str), now, job_id),
                        )
                        if done and _is_complete_result(req.get("result")):
                            # Fixed-delay recurrence anchors on when the run actually
                            # completed (persisted requests.updated_at), not on the
                            # restart time, so the successor is due at
                            # completion + interval rather than restart + interval.
                            completed_at = req.get("updated_at")
                            if not isinstance(completed_at, (int, float)) or isinstance(completed_at, bool):
                                completed_at = now
                            job_row = conn.execute(
                                "SELECT * FROM scheduled_jobs WHERE job_id = ?", (job_id,)
                            ).fetchone()
                            if job_row is not None:
                                self._spawn_successor_locked(conn, job_row, completed_at=float(completed_at))
                    else:
                        conn.execute(
                            """UPDATE scheduled_jobs
                               SET status = 'interrupted',
                                   result_json = ?,
                                   completed_at = ?
                               WHERE job_id = ? AND status = 'claimed'""",
                            (json.dumps({
                                "ok": False,
                                "error": "Gateway restarted while this scheduled job was claimed; "
                                         "no tool was replayed. Review before re-running.",
                                "run_id": run_id,
                            }, default=str), now, job_id),
                        )
                    reconciled.append(job_id)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return reconciled

    @staticmethod
    def fingerprint(prompt: str, extra: Mapping[str, Any] | None = None) -> str:
        blob = json.dumps({"prompt": prompt, **(extra or {})}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def create_session(
        self,
        *,
        title: str = "New Session",
        workspace: str = "",
        metadata: Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO sessions(session_id, title, workspace, status, metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, 'idle', ?, ?, ?)""",
                (sid, title, workspace, json.dumps(dict(metadata or {})), now, now),
            )
        return self.get_session(sid) or {}

    def main_chat_session(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            now = time.time()
            conn.execute(
                """INSERT OR IGNORE INTO sessions(
                    session_id, title, workspace, status, metadata_json, created_at, updated_at
                ) VALUES (?, 'Jaeger Chat', '', 'idle', '{}', ?, ?)""",
                (MAIN_CHAT_SESSION_ID, now, now),
            )
        return self.get_session(MAIN_CHAT_SESSION_ID) or {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "workspace": row["workspace"],
            "status": row["status"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {
                "session_id": r["session_id"],
                "title": r["title"],
                "workspace": r["workspace"],
                "status": r["status"],
                "metadata": json.loads(r["metadata_json"] or "{}"),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def set_session_status(self, session_id: str, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, time.time(), session_id),
            )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> int:
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages(session_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, json.dumps(dict(metadata or {}), default=str), now),
            )
            conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
            return int(cur.lastrowid or 0)

    @staticmethod
    def _bounded_channel_string(value: Any, field: str, max_len: int) -> str:
        """Validate one bounded, non-empty external-channel string field."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        if len(value) > max_len:
            raise ValueError(f"{field} exceeds maximum length of {max_len} characters")
        return value

    def external_channel_destination(self, session_id: str) -> tuple[str, str] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT channel, external_thread_id FROM external_channel_threads WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return (row["channel"], row["external_thread_id"]) if row is not None else None

    def ingest_channel_message(
        self,
        channel: str,
        external_thread_id: str,
        external_message_id: str,
        sender: str,
        body: str,
    ) -> dict[str, Any]:
        """Attribute one inbound external-channel message to a dedicated Gateway session.

        Fully atomic (BEGIN IMMEDIATE): validates bounded strings, claims the
        (channel, external_thread_id, external_message_id) dedup key, allocates
        exactly one Gateway session per (channel, external_thread_id), and
        appends a single role='external' transcript row marked untrusted with
        provenance. The caller never supplies a Gateway session_id; it is
        always allocated here. Bodies and provenance are scrubbed with
        jaeger_authority redaction before persistence; only a one-way content
        digest of the raw payload is stored alongside the redacted content.

        A retry with an identical payload returns the same row with
        ``replayed=True`` and writes nothing; a conflicting replay of the same
        key raises RequestConflictError without any writes. No model, tools,
        outbound effects, network, or automatic activation occur here.
        """
        channel = self._bounded_channel_string(channel, "channel", _CHANNEL_ID_MAX)
        external_thread_id = self._bounded_channel_string(
            external_thread_id, "external_thread_id", _EXTERNAL_ID_MAX
        )
        external_message_id = self._bounded_channel_string(
            external_message_id, "external_message_id", _EXTERNAL_ID_MAX
        )
        sender = self._bounded_channel_string(sender, "sender", _SENDER_MAX)
        if not isinstance(body, str) or not body.strip():
            raise ValueError("body must be a non-empty string")
        if len(body) > _CHANNEL_BODY_MAX:
            raise ValueError(f"body exceeds maximum length of {_CHANNEL_BODY_MAX} characters")

        # Stable, one-way digest over the canonical raw payload; safe to persist
        # because it reveals nothing about the content itself.
        digest = hashlib.sha256(
            json.dumps(
                {
                    "channel": channel,
                    "external_thread_id": external_thread_id,
                    "external_message_id": external_message_id,
                    "sender": sender,
                    "body": body,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    """SELECT session_id, message_row_id, sender, content_digest FROM external_channel_messages
                       WHERE channel = ? AND external_thread_id = ? AND external_message_id = ?""",
                    (channel, external_thread_id, external_message_id),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["content_digest"] != digest
                        or existing["sender"] != redact_text(sender)[:_SENDER_MAX]
                    ):
                        conn.rollback()
                        raise RequestConflictError(
                            f"external message {external_message_id!r} on channel {channel!r} "
                            f"thread {external_thread_id!r} already ingested with a different payload"
                        )
                    conn.rollback()
                    return {
                        "session_id": existing["session_id"],
                        "message_id": external_message_id,
                        "message_row_id": int(existing["message_row_id"]),
                        "replayed": True,
                    }

                thread = conn.execute(
                    """SELECT session_id FROM external_channel_threads
                       WHERE channel = ? AND external_thread_id = ?""",
                    (channel, external_thread_id),
                ).fetchone()
                if thread is not None:
                    session_id = thread["session_id"]
                else:
                    # Allocated here only — never accepted from the caller — and
                    # inserted under the same write lock as the message claim, so
                    # concurrent connections cannot allocate two sessions for one
                    # (channel, external_thread_id) pair.
                    session_id = f"sess_{uuid.uuid4().hex[:12]}"
                    conn.execute(
                        """INSERT INTO sessions(session_id, title, workspace, status, metadata_json, created_at, updated_at)
                           VALUES (?, ?, '', 'idle', ?, ?, ?)""",
                        (
                            session_id,
                            f"External {channel} thread",
                            json.dumps(
                                redact_object(
                                    {
                                        "source": "external_channel",
                                        "channel": channel,
                                        "external_thread_id": external_thread_id,
                                        "trust": "untrusted",
                                    }
                                ),
                                default=str,
                            ),
                            now,
                            now,
                        ),
                    )
                    conn.execute(
                        """INSERT INTO external_channel_threads(channel, external_thread_id, session_id, created_at)
                           VALUES (?, ?, ?, ?)""",
                        (channel, external_thread_id, session_id, now),
                    )

                provenance = redact_object(
                    {
                        "source": "external_channel",
                        "channel": channel,
                        "external_thread_id": external_thread_id,
                        "external_message_id": external_message_id,
                        "sender": sender,
                        "untrusted": True,
                        "trust": "untrusted",
                    }
                )
                cur = conn.execute(
                    "INSERT INTO messages(session_id, role, content, metadata_json, created_at) VALUES (?, 'external', ?, ?, ?)",
                    (
                        session_id,
                        redact_text(body)[:_CHANNEL_BODY_MAX],
                        json.dumps(provenance, default=str),
                        now,
                    ),
                )
                message_row_id = int(cur.lastrowid or 0)
                conn.execute(
                    """INSERT INTO external_channel_messages(
                           channel, external_thread_id, external_message_id, session_id,
                           message_row_id, sender, content_digest, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        channel,
                        external_thread_id,
                        external_message_id,
                        session_id,
                        message_row_id,
                        redact_text(sender)[:_SENDER_MAX],
                        digest,
                        now,
                    ),
                )
                conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {
            "session_id": session_id,
            "message_id": external_message_id,
            "message_row_id": message_row_id,
            "replayed": False,
        }

    def list_chat_topics(self, query: str = "", *, limit: int = 100, include_external: bool = True) -> list[dict[str, Any]]:
        """Index user turns by their transcript position, without generating topics."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT m.id, m.created_at, substr(m.content, 1, 300) AS excerpt
                   FROM messages m JOIN sessions s ON s.session_id = m.session_id
                   WHERE m.role = 'user' AND (? = '' OR instr(lower(m.content), lower(?)) > 0)
                   AND (? OR json_extract(s.metadata_json, '$.source') IS NOT 'external_channel')
                   ORDER BY m.id DESC LIMIT ?""",
                (query, query, include_external, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def list_messages(self, session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
                (session_id, max(1, int(limit))),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": r["content"],
                "metadata": json.loads(r["metadata_json"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def admit_request(
        self,
        session_id: str,
        prompt: str,
        *,
        request_id: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Idempotent request admission returning ``(record, is_replay)``."""
        rid = request_id or f"req_{uuid.uuid4().hex[:12]}"
        fp = self.fingerprint(prompt, extra)
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM requests WHERE request_id = ?", (rid,)).fetchone()
            if row is not None:
                if row["fingerprint"] != fp:
                    raise RequestConflictError(f"request_id {rid!r} already used with different payload")
                return {
                    "request_id": row["request_id"],
                    "session_id": row["session_id"],
                    "status": row["status"],
                    "result": json.loads(row["result_json"] or "{}"),
                }, True
            conn.execute(
                """INSERT INTO requests(request_id, session_id, fingerprint, status, result_json, created_at, updated_at)
                   VALUES (?, ?, ?, 'queued', '{}', ?, ?)""",
                (rid, session_id, fp, now, now),
            )
        return {"request_id": rid, "session_id": session_id, "status": "queued", "result": {}}, False

    def settle_request(self, request_id: str, status: str, result: Mapping[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE requests SET status = ?, result_json = ?, updated_at = ? WHERE request_id = ?",
                (status, json.dumps(dict(result), default=str), time.time(), request_id),
            )

    def create_approval(self, session_id: str, tool_name: str, prompt: str) -> dict[str, Any]:
        aid = f"apr_{uuid.uuid4().hex[:10]}"
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO approvals(approval_id, session_id, tool_name, prompt, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (aid, session_id, tool_name, prompt, now),
            )
        return {
            "approval_id": aid,
            "session_id": session_id,
            "tool_name": tool_name,
            "prompt": prompt,
            "status": "pending",
            "created_at": now,
        }

    @staticmethod
    def _insert_pending_job(
        conn: sqlite3.Connection, jid: str, session_id: str, prompt: str, due_at: float,
        meta: dict[str, Any], now: float, series_id: str | None, interval_s: float | None,
    ) -> None:
        conn.execute(
            """INSERT INTO scheduled_jobs(job_id, session_id, prompt, due_at, status,
                                           result_json, metadata_json, created_at,
                                           series_id, interval_s, predecessor_job_id, fire_seq)
               VALUES (?, ?, ?, ?, 'pending', '{}', ?, ?, ?, ?, NULL, 0)""",
            (jid, session_id, prompt, float(due_at), json.dumps(meta, default=str), now,
             series_id, interval_s),
        )
        if series_id is not None:
            # Effective default state for a new (and any pre-existing) series
            # row is 'active'; recorded explicitly so get_series_status and
            # the claim/spawn guards see it.
            conn.execute(
                """INSERT OR IGNORE INTO series_controls(series_id, session_id, status, updated_at)
                   VALUES (?, ?, 'active', ?)""",
                (series_id, session_id, now),
            )

    def propose_scheduled_job(
        self, session_id: str, *, prompt: str, due_at: Any, interval_s: float | None = None,
    ) -> dict[str, Any]:
        """Persist an immutable scheduled job proposal for explicit owner approval."""
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000:
            raise ValueError("prompt must be 1-16000 characters")
        if isinstance(due_at, bool) or not isinstance(due_at, (int, float)):
            raise ValueError("finite numeric due_at is required")
        try:
            due = float(due_at)
        except OverflowError:
            raise ValueError("finite numeric due_at is required") from None
        if not math.isfinite(due):
            raise ValueError("finite numeric due_at is required")
        if interval_s is not None and (
            isinstance(interval_s, bool) or not isinstance(interval_s, (int, float))
            or not 1 <= interval_s <= 31536000
        ):
            raise ValueError("interval_s must be within 1 to 31536000 seconds")
        payload = {"prompt": prompt.strip(), "due_at": due, "interval_s": interval_s}
        return self.create_approval(session_id, "schedule-proposal", json.dumps(payload))

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        """Get an approval by ID for owner authorization checking."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return dict(row) if row is not None else None

    def resolve_approval(
        self, approval_id: str, *, decision: str, note: str = "", allow_schedule_approval: bool = False,
    ) -> dict[str, Any] | None:
        now = time.time()
        status = "approved" if decision.lower() in ("approve", "approved", "allow", "yes") else "denied"
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ? AND status = 'pending'", (approval_id,),
            ).fetchone()
            if row is None:
                return None
            job_id = None
            if row["tool_name"] == "schedule-proposal":
                if not allow_schedule_approval:
                    return None
                if status == "approved":
                    payload = json.loads(row["prompt"])
                    interval = payload["interval_s"]
                    job_id = f"job_{approval_id}"
                    series_id = f"series_{approval_id}" if interval is not None else None
                    meta = {} if interval is None else {
                        "series_id": series_id, "interval_s": interval, "fire_seq": 0,
                        "recurrence": {"kind": "fixed_delay", "interval_s": interval},
                    }
                    self._insert_pending_job(
                        conn, job_id, row["session_id"], payload["prompt"], payload["due_at"],
                        meta, now, series_id, interval,
                    )
            conn.execute(
                "UPDATE approvals SET status = ?, decision = ?, note = ?, resolved_at = ? WHERE approval_id = ?",
                (status, decision, note, now, approval_id),
            )
            resolved = dict(row) | {"status": status, "decision": decision, "note": note, "resolved_at": now}
            return resolved if job_id is None else resolved | {"job_id": job_id}

    def list_pending_approvals(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' AND session_id = ? ORDER BY created_at ASC",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC"
                ).fetchall()
        return [dict(r) for r in rows]


__all__ = ["GatewayStore", "RequestConflictError"]
