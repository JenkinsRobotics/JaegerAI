"""Standalone WAL SQLite Gateway store for sessions, transcripts, idempotent requests & approvals."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping


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
                """
            )

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

    def resolve_approval(self, approval_id: str, *, decision: str, note: str = "") -> dict[str, Any] | None:
        now = time.time()
        status = "approved" if decision.lower() in ("approve", "approved", "allow", "yes") else "denied"
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """UPDATE approvals
                   SET status = ?, decision = ?, note = ?, resolved_at = ?
                   WHERE approval_id = ? AND status = 'pending'""",
                (status, decision, note, now, approval_id),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        return dict(row) if row is not None else None

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
