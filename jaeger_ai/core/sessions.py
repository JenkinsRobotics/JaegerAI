"""SQLite conversation persistence — sessions survive app close.

The agent's live history is in-memory (``_session_histories``); when the app
or a window closes, it's gone. This records every turn (user + reply) to
``<instance>/memory/sessions.db`` so conversations are durable and
listable — the foundation for resume/search (the Hermes session model).

Self-contained: its own WAL connection, thread-safe (the agent worker
records while a surface lists). Recording is best-effort — a DB hiccup
never breaks a turn.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    preview     TEXT,
    created_at  REAL,
    last_active REAL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL,
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


class SessionStore:
    """Durable conversation history keyed by ``session_id``."""

    def __init__(self, db_path: Path | str) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def record(self, session_id: str, role: str, text: str) -> None:
        """Append one message; upsert the session (first user line = preview)."""
        if not session_id or not text:
            return
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_at, last_active) "
                "VALUES(?,?,?)", (session_id, now, now))
            self._conn.execute(
                "INSERT INTO messages(session_id, role, text, ts) VALUES(?,?,?,?)",
                (session_id, role, text, now))
            if role == "user":
                self._conn.execute(
                    "UPDATE sessions SET last_active=?, "
                    "preview=COALESCE(preview, ?) WHERE id=?",
                    (now, text[:100], session_id))
            else:
                self._conn.execute(
                    "UPDATE sessions SET last_active=? WHERE id=?",
                    (now, session_id))

    def history(self, session_id: str) -> list[dict[str, Any]]:
        """All turns for a session, oldest first."""
        cur = self._conn.execute(
            "SELECT role, text, ts FROM messages WHERE session_id=? ORDER BY id",
            (session_id,))
        return [{"role": r, "text": t, "ts": ts} for r, t, ts in cur.fetchall()]

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Recent sessions (most-active first) with preview + turn count.
        Ties on ``last_active`` (two turns landing in the same wall-clock
        tick) break by insertion order (``rowid``, newest first) so
        ranking stays deterministic instead of depending on SQLite's
        unspecified tie order."""
        cur = self._conn.execute(
            "SELECT s.id, s.title, s.preview, s.created_at, s.last_active, "
            "  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) "
            "FROM sessions s ORDER BY s.last_active DESC, s.rowid DESC "
            "LIMIT ?", (limit,))
        return [{"id": i, "title": ti, "preview": p, "created_at": ca,
                 "last_active": la, "messages": n}
                for i, ti, p, ca, la, n in cur.fetchall()]

    def set_title(self, session_id: str, title: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE sessions SET title=? WHERE id=?",
                               (title, session_id))

    def prune(self, keep: int) -> int:
        """Drop sessions beyond the ``keep`` most-recently-active (and their
        messages), so a long-lived install doesn't grow this file forever.
        ``keep <= 0`` is a no-op — unlimited retention is an explicit
        operator choice (``display.session_history_keep``), not a silently
        ignored value. Returns the number of sessions dropped."""
        if keep <= 0:
            return 0
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT id FROM sessions ORDER BY last_active DESC, "
                "rowid DESC LIMIT -1 OFFSET ?", (keep,))
            stale = [row[0] for row in cur.fetchall()]
            if not stale:
                return 0
            self._conn.executemany(
                "DELETE FROM messages WHERE session_id=?",
                [(s,) for s in stale])
            self._conn.executemany(
                "DELETE FROM sessions WHERE id=?", [(s,) for s in stale])
        return len(stale)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ── lazy per-instance singleton ───────────────────────────────────
_active: dict[str, Any] = {"path": None, "store": None}


def get_store(layout: Any = None) -> SessionStore | None:
    """The session store for the active instance, or None if no instance is
    bound. Reuses one connection per DB path."""
    if layout is None:
        from jaeger_ai.main import _pipeline
        layout = _pipeline.get("layout")
    if layout is None:
        return None
    path = str(layout.memory_dir / "sessions.db")
    if _active["path"] == path and _active["store"] is not None:
        return _active["store"]
    if _active["store"] is not None:
        try:
            _active["store"].close()
        except Exception:  # noqa: BLE001
            pass
    layout.memory_dir.mkdir(parents=True, exist_ok=True)
    _active["store"] = SessionStore(Path(path))
    _active["path"] = path
    return _active["store"]


def reset_for_tests() -> None:
    if _active["store"] is not None:
        try:
            _active["store"].close()
        except Exception:  # noqa: BLE001
            pass
    _active["path"] = None
    _active["store"] = None
