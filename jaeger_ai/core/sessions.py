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

import json
import re
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
CREATE TABLE IF NOT EXISTS session_tombstones (
    id         TEXT PRIMARY KEY,
    deleted_at REAL NOT NULL
);
"""

SESSION_CONTRACT_VERSION = 3
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,255}$")
_HEX_ID_RE = re.compile(r"^[0-9a-f]+$")

# Surfaces that actually talk to Jaeger. ARES maps tui/app/cli/acp into its
# CLI tab; webui stays in WebUI. First writer wins — later turns cannot
# re-tag a conversation started on another surface.
KNOWN_ORIGINS = frozenset({
    "webui", "tui", "app", "cli", "acp",
    "telegram", "discord", "imessage", "slack", "weixin", "email", "matrix",
    "cron", "webhook", "mcp", "voice", "kanban", "worker", "completions",
    "probe", "deepthink", "claude", "codex", "grok", "gemini", "hermes",
    "openclaw", "ares", "unknown",
})
_PREFIX_ORIGINS = frozenset({
    "telegram", "discord", "imessage", "slack", "weixin", "email", "matrix",
})
_EXACT_ORIGINS = {
    "cli": "tui",
    "tui": "tui",
    "desktop-app": "app",
    "gui": "app",
    "webhook": "webhook",
    "voice": "voice",
    "mcp": "mcp",
    "kanban": "kanban",
    "kanban_idle": "kanban",
    "completions": "completions",
    "worker": "worker",
    "default": "probe",
    "test_probe": "probe",
}


def canonical_session_id(value: object) -> str:
    """Return the shared opaque id used by every session-contract operation."""
    session_id = str(value or "").strip()
    if not session_id or not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("invalid session id")
    return session_id


def normalize_session_origin(value: object) -> str:
    """Return a known origin tag, or ``unknown``."""
    origin = str(value or "").strip().lower()
    if origin == "cli":
        return "tui"
    if origin in KNOWN_ORIGINS:
        return origin
    return "unknown"


def infer_session_origin(session_id: str, explicit: object = None) -> str:
    """Classify which surface minted ``session_id``.

    TUI uses the stable key ``cli``. The Swift/PySide apps mint 8-char
    hex ids (and historically ``desktop-app``). ARES WebUI mints 12-char
    hex ids. Explicit ``source``/``origin`` from the wire wins when set.
    """
    if explicit not in (None, ""):
        origin = normalize_session_origin(explicit)
        if origin != "unknown":
            return origin
    key = str(session_id or "").strip().lower()
    if not key:
        return "unknown"
    mapped = _EXACT_ORIGINS.get(key)
    if mapped:
        return mapped
    if key.startswith("health_probe"):
        return "probe"
    if key.startswith("deepthink"):
        return "deepthink"
    if key.startswith("cron:") or key.startswith("cron_"):
        return "cron"
    if ":" in key:
        prefix = key.split(":", 1)[0]
        if prefix in _PREFIX_ORIGINS:
            return prefix
    if _HEX_ID_RE.fullmatch(key):
        if len(key) == 8:
            return "app"
        if len(key) == 12:
            return "webui"
    return "unknown"


class SessionStore:
    """Durable conversation history keyed by ``session_id``."""

    def __init__(self, db_path: Path | str) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._ensure_brain_columns()
            self._ensure_contract_columns()
            self._redact_existing_messages()
            self._conn.execute(
                "UPDATE sessions SET execution_state='interrupted' "
                "WHERE execution_state='running'"
            )

    def _ensure_brain_columns(self) -> None:
        """Sessions record the brain that served them so get_mode /
        History answer from this conversation, not a process-global
        preset."""
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")
        }
        if "model" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN model TEXT")
        if "provider" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN provider TEXT")

    def _ensure_contract_columns(self) -> None:
        session_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")
        }
        if "execution_state" not in session_cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN execution_state TEXT "
                "DEFAULT 'idle'"
            )
        if "origin" not in session_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN origin TEXT")
        message_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(messages)")
        }
        if "metadata" not in message_cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        self._backfill_origins()

    def _backfill_origins(self) -> None:
        rows = self._conn.execute(
            "SELECT id FROM sessions WHERE origin IS NULL OR origin=''"
        ).fetchall()
        if not rows:
            return
        self._conn.executemany(
            "UPDATE sessions SET origin=? WHERE id=?",
            [(infer_session_origin(session_id), session_id) for (session_id,) in rows],
        )

    def _stamp_origin_locked(self, session_id: str, explicit: object = None) -> str:
        """Set origin on first write only. Returns the durable tag."""
        origin = infer_session_origin(session_id, explicit)
        self._conn.execute(
            "UPDATE sessions SET origin=? WHERE id=? AND (origin IS NULL OR origin='')",
            (origin, session_id),
        )
        row = self._conn.execute(
            "SELECT origin FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        return str(row[0] if row and row[0] else origin)

    def _redact_existing_messages(self) -> None:
        """One-way migration: remove credential-shaped values from history."""
        from jaeger_ai.core.redaction import redact_text, redact_value

        rows = self._conn.execute("SELECT id, text, metadata FROM messages").fetchall()
        updates: list[tuple[str, str | None, int]] = []
        for message_id, text, metadata in rows:
            safe_text = redact_text(str(text or ""))
            safe_metadata = metadata
            if metadata:
                try:
                    safe_metadata = json.dumps(
                        redact_value(json.loads(metadata)), ensure_ascii=False
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    safe_metadata = redact_text(str(metadata))
            if safe_text != text or safe_metadata != metadata:
                updates.append((safe_text, safe_metadata, message_id))
        self._conn.executemany(
            "UPDATE messages SET text=?, metadata=? WHERE id=?", updates
        )
        previews = self._conn.execute(
            "SELECT id, preview FROM sessions WHERE preview IS NOT NULL"
        ).fetchall()
        self._conn.executemany(
            "UPDATE sessions SET preview=? WHERE id=?",
            [
                (safe, session_id)
                for session_id, preview in previews
                if (safe := redact_text(str(preview))) != preview
            ],
        )

    def record(
        self,
        session_id: str,
        role: str,
        text: str,
        *,
        model: str | None = None,
        provider: str | None = None,
        metadata: dict[str, Any] | None = None,
        origin: str | None = None,
    ) -> None:
        """Append one message; upsert the session (first user line = preview)."""
        if not session_id or not text:
            return
        try:
            session_id = canonical_session_id(session_id)
        except ValueError:
            return
        from jaeger_ai.core.redaction import redact_text, redact_value

        text = redact_text(str(text))
        metadata = redact_value(metadata) if metadata else None
        now = time.time()
        stamped = infer_session_origin(session_id, origin)
        with self._lock, self._conn:
            if self._is_tombstoned_locked(session_id):
                return
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions(id, created_at, last_active, origin) "
                "VALUES(?,?,?,?)", (session_id, now, now, stamped))
            self._stamp_origin_locked(session_id, origin)
            self._conn.execute(
                "INSERT INTO messages(session_id, role, text, ts, metadata) "
                "VALUES(?,?,?,?,?)",
                (
                    session_id, role, text, now,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                ))
            if role == "user":
                self._conn.execute(
                    "UPDATE sessions SET last_active=?, "
                    "preview=COALESCE(preview, ?) WHERE id=?",
                    (now, text[:100], session_id))
            else:
                self._conn.execute(
                    "UPDATE sessions SET last_active=? WHERE id=?",
                    (now, session_id))
            self._conn.execute(
                "UPDATE sessions SET execution_state='idle' WHERE id=?",
                (session_id,),
            )
            if model or provider:
                self._conn.execute(
                    "UPDATE sessions SET model=COALESCE(?, model), "
                    "provider=COALESCE(?, provider) WHERE id=?",
                    (model or None, provider or None, session_id),
                )

    def import_transcript(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        title: str = "",
        model: str = "",
        provider: str = "",
        origin: str = "unknown",
    ) -> dict[str, Any]:
        """Atomically import one external transcript exactly once.

        Unlike repeated calls to :meth:`record`, this preserves source
        timestamps and cannot leave a half-imported session after a failure.
        Existing sessions and tombstones are never overwritten.
        """
        session_id = canonical_session_id(session_id)
        from jaeger_ai.core.redaction import redact_text, redact_value

        clean: list[tuple[str, str, float, str | None]] = []
        for row in messages:
            role = str(row.get("role") or "").strip().lower()
            if role not in {"user", "assistant", "system", "tool", "reasoning"}:
                continue
            text = redact_text(str(row.get("text") or row.get("content") or ""))
            if not text:
                continue
            try:
                ts = float(row.get("ts") or row.get("timestamp") or time.time())
            except (TypeError, ValueError):
                ts = time.time()
            metadata = redact_value(row.get("metadata") or {})
            clean.append((
                role,
                text,
                ts,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
            ))
        if not clean:
            raise ValueError("transcript has no importable messages")
        created_at = min(row[2] for row in clean)
        last_active = max(row[2] for row in clean)
        stamped = normalize_session_origin(origin)
        with self._lock, self._conn:
            if self._is_tombstoned_locked(session_id):
                return {"id": session_id, "created": False, "tombstoned": True}
            if self._conn.execute(
                "SELECT 1 FROM sessions WHERE id=?", (session_id,)
            ).fetchone() is not None:
                return {"id": session_id, "created": False, "tombstoned": False}
            first_user = next((row[1] for row in clean if row[0] == "user"), clean[0][1])
            self._conn.execute(
                "INSERT INTO sessions"
                "(id,title,preview,created_at,last_active,model,provider,execution_state,origin) "
                "VALUES(?,?,?,?,?,?,?,'idle',?)",
                (
                    session_id,
                    redact_text(title)[:500] or first_user[:100],
                    first_user[:100],
                    created_at,
                    last_active,
                    model or None,
                    provider or None,
                    stamped,
                ),
            )
            self._conn.executemany(
                "INSERT INTO messages(session_id,role,text,ts,metadata) VALUES(?,?,?,?,?)",
                [(session_id, *row) for row in clean],
            )
        return {
            "id": session_id,
            "created": True,
            "tombstoned": False,
            "messages": len(clean),
        }

    def stamp_brain(
        self,
        session_id: str,
        *,
        model: str | None,
        provider: str | None,
    ) -> None:
        """Remember which brain served this conversation. No new message."""
        if not session_id or not (model or provider):
            return
        session_id = canonical_session_id(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET model=COALESCE(?, model), "
                "provider=COALESCE(?, provider) WHERE id=?",
                (model or None, provider or None, session_id),
            )

    def brain(self, session_id: str) -> dict[str, str | None]:
        """The model/provider last stamped on this session, if any."""
        if not session_id:
            return {"model": None, "provider": None}
        session_id = canonical_session_id(session_id)
        with self._lock:
            cur = self._conn.execute(
                "SELECT model, provider FROM sessions WHERE id=?",
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"model": None, "provider": None}
        return {"model": row[0], "provider": row[1]}

    def history(self, session_id: str) -> list[dict[str, Any]]:
        """All turns for a session, oldest first."""
        session_id = canonical_session_id(session_id)
        cur = self._conn.execute(
            "SELECT role, text, ts, metadata FROM messages "
            "WHERE session_id=? ORDER BY id",
            (session_id,))
        rows = []
        for role, text, ts, metadata in cur.fetchall():
            row = {"role": role, "text": text, "ts": ts}
            if metadata:
                try:
                    parsed = json.loads(metadata)
                except (TypeError, ValueError):
                    parsed = None
                if isinstance(parsed, dict):
                    row["metadata"] = parsed
            rows.append(row)
        return rows

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Recent sessions (most-active first) with preview + turn count.
        Ties on ``last_active`` (two turns landing in the same wall-clock
        tick) break by insertion order (``rowid``, newest first) so
        ranking stays deterministic instead of depending on SQLite's
        unspecified tie order."""
        cur = self._conn.execute(
            "SELECT s.id, s.title, s.preview, s.created_at, s.last_active, "
            "  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id), "
            "  s.model, s.provider, s.execution_state, s.origin "
            "FROM sessions s ORDER BY s.last_active DESC, s.rowid DESC "
            "LIMIT ?", (limit,))
        rows = []
        for i, ti, p, ca, la, n, model, provider, state, origin in cur.fetchall():
            tagged = origin or infer_session_origin(i)
            rows.append({
                "id": i, "title": ti, "preview": p, "created_at": ca,
                "last_active": la, "messages": n, "model": model,
                "provider": provider, "execution_state": state or "idle",
                "origin": tagged, "source": tagged,
            })
        return rows

    def create(self, session_id: str, origin: str | None = None) -> dict[str, Any]:
        """Idempotently create one transcript unless its id is tombstoned."""
        session_id = canonical_session_id(session_id)
        now = time.time()
        stamped = infer_session_origin(session_id, origin)
        with self._lock, self._conn:
            if self._is_tombstoned_locked(session_id):
                return {"id": session_id, "created": False, "tombstoned": True,
                        "origin": stamped}
            existed = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id=?", (session_id,)
            ).fetchone() is not None
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions"
                "(id, created_at, last_active, execution_state, origin) "
                "VALUES(?,?,?,'idle',?)", (session_id, now, now, stamped),
            )
            tagged = self._stamp_origin_locked(session_id, origin)
        return {
            "id": session_id, "created": not existed, "tombstoned": False,
            "origin": tagged,
        }

    def exists(self, session_id: str) -> bool:
        session_id = canonical_session_id(session_id)
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM sessions WHERE id=?", (session_id,)
            ).fetchone() is not None

    def set_execution_state(self, session_id: str, state: str) -> bool:
        session_id = canonical_session_id(session_id)
        normalized = str(state or "").strip().lower()
        if normalized not in {"idle", "running", "interrupted", "failed"}:
            raise ValueError("invalid execution state")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET execution_state=?, last_active=? WHERE id=?",
                (normalized, time.time(), session_id),
            )
        return cur.rowcount > 0

    def set_title(self, session_id: str, title: str) -> bool:
        session_id = canonical_session_id(session_id)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET title=? WHERE id=?", (title, session_id)
            )
        return cur.rowcount > 0

    def clear(self, session_id: str) -> bool:
        """Idempotently clear runtime history while retaining the session."""
        session_id = canonical_session_id(session_id)
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id=?", (session_id,)
            ).fetchone() is not None
            if not exists:
                return False
            self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            self._conn.execute(
                "UPDATE sessions SET preview=NULL, execution_state='idle', "
                "last_active=? WHERE id=?", (time.time(), session_id),
            )
        return exists

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """Search canonical transcript text and runtime titles."""
        needle = str(query or "").strip()
        if not needle:
            return self.list_sessions(limit=limit)
        escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        with self._lock:
            cur = self._conn.execute(
                "SELECT DISTINCT s.id FROM sessions s LEFT JOIN messages m "
                "ON m.session_id=s.id WHERE s.title LIKE ? ESCAPE '\\' "
                "OR s.preview LIKE ? ESCAPE '\\' OR m.text LIKE ? ESCAPE '\\' "
                "ORDER BY s.last_active DESC LIMIT ?",
                (pattern, pattern, pattern, max(1, min(int(limit), 500))),
            )
            ids = [row[0] for row in cur.fetchall()]
        if not ids:
            return []
        rows = {row["id"]: row for row in self.list_sessions(limit=100_000)}
        return [rows[i] for i in ids if i in rows]

    def reconcile_visible_transcript(
        self, session_id: str, messages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Replace wrapped user prompts with their ARES-visible text safely.

        Roles and assistant text must already match exactly after whitespace
        normalization. This migration cannot rewrite model output or change the
        number/order of turns.
        """
        session_id = canonical_session_id(session_id)
        proposed = [
            (str(row.get("role") or ""), str(row.get("text") or ""))
            for row in messages
            if isinstance(row, dict) and row.get("role") in {"user", "assistant"}
        ]
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT id, role, text FROM messages WHERE session_id=? "
                "AND role IN ('user','assistant') ORDER BY id", (session_id,),
            ).fetchall()
            if len(current) != len(proposed):
                raise ValueError("transcript message counts do not match")
            updates = []
            for (message_id, current_role, current_text), (new_role, new_text) in zip(
                current, proposed
            ):
                if current_role != new_role:
                    raise ValueError("transcript roles do not match")
                if new_role == "assistant" and " ".join(current_text.split()) != " ".join(new_text.split()):
                    raise ValueError("assistant transcript text does not match")
                if new_role == "user" and not new_text.strip():
                    raise ValueError("user transcript text cannot be empty")
                if new_role == "user" and current_text != new_text:
                    updates.append((new_text, message_id))
            self._conn.executemany("UPDATE messages SET text=? WHERE id=?", updates)
            if proposed:
                first_user = next((text for role, text in proposed if role == "user"), None)
                if first_user is not None:
                    self._conn.execute(
                        "UPDATE sessions SET preview=? WHERE id=?",
                        (first_user[:100], session_id),
                    )
        return {"id": session_id, "updated_user_messages": len(updates)}

    def reconcile_visible_user_messages(
        self, session_id: str, user_messages: list[str]
    ) -> dict[str, Any]:
        """Reconcile visible user text when ARES deduplicated assistant rows."""
        session_id = canonical_session_id(session_id)
        proposed = [str(text) for text in user_messages]
        if any(not text.strip() for text in proposed):
            raise ValueError("user transcript text cannot be empty")
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT id, text FROM messages WHERE session_id=? AND role='user' "
                "ORDER BY id", (session_id,),
            ).fetchall()
            if len(current) != len(proposed):
                raise ValueError("user transcript message counts do not match")
            updates = [
                (new_text, message_id)
                for (message_id, current_text), new_text in zip(current, proposed)
                if current_text != new_text
            ]
            self._conn.executemany("UPDATE messages SET text=? WHERE id=?", updates)
            if proposed:
                self._conn.execute(
                    "UPDATE sessions SET preview=? WHERE id=?",
                    (proposed[0][:100], session_id),
                )
        return {"id": session_id, "updated_user_messages": len(updates)}

    def delete(self, session_id: str) -> bool:
        """Idempotently delete and tombstone one canonical transcript."""
        session_id = canonical_session_id(session_id)
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id=?", (session_id,),
            ).fetchone() is not None
            self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            self._conn.execute(
                "INSERT INTO session_tombstones(id, deleted_at) VALUES(?,?) "
                "ON CONFLICT(id) DO UPDATE SET deleted_at=excluded.deleted_at",
                (session_id, time.time()),
            )
        return exists

    def is_tombstoned(self, session_id: str) -> bool:
        session_id = canonical_session_id(session_id)
        with self._lock:
            return self._is_tombstoned_locked(session_id)

    def _is_tombstoned_locked(self, session_id: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM session_tombstones WHERE id=?", (session_id,)
        ).fetchone() is not None

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
