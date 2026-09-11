"""Persistent SQLite Session Store for Jaeger Gateway.

Stores conversations, transcripts, and active run status independently of any
connected UI window. Modeled after OpenClaw's durable session catalog.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


def default_store_path() -> Path:
    """Return the durable database path in ~/.jaeger/gateway_sessions.sqlite3."""
    home = Path(os.environ.get("JAEGER_HOME", str(Path.home() / ".jaeger")))
    home.mkdir(parents=True, exist_ok=True)
    return home / "gateway_sessions.sqlite3"


class GatewaySessionStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    profile TEXT NOT NULL DEFAULT 'jaeger',
                    workspace TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'idle',
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    tool_calls_json TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);
            """)

    def list_sessions(self, profile: str | None = None) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            query = "SELECT s.*, COUNT(m.id) as message_count FROM sessions s LEFT JOIN messages m ON s.session_id = m.session_id"
            params: list[Any] = []
            if profile:
                query += " WHERE s.profile = ?"
                params.append(profile)
            query += " GROUP BY s.session_id ORDER BY s.updated_at DESC"
            rows = conn.execute(query, params).fetchall()
            out = []
            for r in rows:
                meta = json.loads(r["metadata_json"] or "{}")
                row = {
                    "session_id": r["session_id"],
                    "title": r["title"],
                    "profile": r["profile"],
                    "workspace": r["workspace"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "status": r["status"],
                    "message_count": r["message_count"],
                    "metadata": meta,
                    "agent_id": meta.get("agent_id"),
                }
                out.append(row)
            return out

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            messages = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC, id ASC",
                (session_id,),
            ).fetchall()
            meta = json.loads(row["metadata_json"] or "{}")
            return {
                "session_id": row["session_id"],
                "title": row["title"],
                "profile": row["profile"],
                "workspace": row["workspace"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "metadata": meta,
                "agent_id": meta.get("agent_id"),
                "messages": [
                    {
                        "id": m["id"],
                        "role": m["role"],
                        "content": m["content"],
                        "timestamp": m["timestamp"],
                        "tool_calls": json.loads(m["tool_calls_json"] or "[]"),
                    }
                    for m in messages
                ],
            }

    def ensure_session(
        self,
        session_id: str,
        *,
        title: str = "New Conversation",
        profile: str = "jaeger",
        workspace: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        meta_str = json.dumps(metadata or {})
        with self._get_conn() as conn:
            if metadata:
                # Merge metadata keys when caller supplies them on ensure.
                existing = conn.execute(
                    "SELECT metadata_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if existing:
                    prior = json.loads(existing["metadata_json"] or "{}")
                    prior.update(metadata)
                    meta_str = json.dumps(prior)
            conn.execute(
                """
                INSERT INTO sessions (session_id, title, profile, workspace, created_at, updated_at, status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, 'idle', ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    metadata_json = CASE
                        WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json
                        ELSE sessions.metadata_json
                    END
                """,
                (session_id, title, profile, workspace, now, now, meta_str),
            )
        return self.get_session(session_id) or {}

    def update_status(self, session_id: str, status: str) -> None:
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, now, session_id),
            )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        timestamp: float | None = None,
    ) -> int:
        now = timestamp or time.time()
        tool_str = json.dumps(tool_calls or [])
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp, tool_calls_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, now, tool_str),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return cursor.lastrowid or 0

    def delete_session(self, session_id: str) -> bool:
        with self._get_conn() as conn:
            res = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            return res.rowcount > 0

    def update_metadata(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Merge ``patch`` into session metadata and return the updated session."""
        session = self.get_session(session_id)
        if session is None:
            return None
        meta = dict(session.get("metadata") or {})
        meta.update(patch or {})
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET metadata_json = ?, updated_at = ? WHERE session_id = ?",
                (json.dumps(meta), now, session_id),
            )
        return self.get_session(session_id)

    def clear_messages(self, session_id: str) -> bool:
        """Drop transcript messages; keep the session row (handoff keep_history=false)."""
        with self._get_conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not exists:
                return False
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (time.time(), session_id),
            )
        return True
