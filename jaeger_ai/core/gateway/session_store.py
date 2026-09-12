"""Persistent SQLite Session Store for Jaeger Gateway.

Stores conversations, transcripts, client request admission, events,
approvals, and active run status independently of any connected UI window.
Modeled after OpenClaw's durable session catalog.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 4
MAX_RETAINED_EVENTS = 5000
REQUEST_ID_MAX = 128


class RequestConflict(ValueError):
    """A client request_id was reused with a different input fingerprint."""


class RequestBusy(RuntimeError):
    """A session already has in-flight or unreconciliation work."""


def default_store_path() -> Path:
    """The durable session database — ``<state root>/gateway_sessions.sqlite3``.

    Resolved through ``operator_state_root()``, the one place that
    implements the documented precedence (``JAEGER_STATE_DIR`` →
    ``JAEGER_HOME`` → ``~/.jaeger``).

    This used to read ``JAEGER_HOME`` directly and ignore
    ``JAEGER_STATE_DIR`` entirely, which meant a test or sandbox that set
    the documented state override still opened the operator's REAL session
    database — and, because the store takes an ownership lease, tripped over
    the live daemon's lock instead of running isolated. The filename is
    unchanged, so an existing database is found exactly where it already is.
    """
    from jaeger_ai.core.instance.instance import operator_state_root

    root = operator_state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "gateway_sessions.sqlite3"


def input_fingerprint(text: str, *, extra: dict[str, Any] | None = None) -> str:
    payload = {"text": text, **(extra or {})}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _row_meta(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class GatewaySessionStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def _immediate(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

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
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
        current = int(row["value"]) if row else 1
        if current < 2:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS client_requests (
                    request_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    native_run_id TEXT,
                    native_session TEXT,
                    status TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    owner_pid INTEGER,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_requests_session
                    ON client_requests(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_requests_turn ON client_requests(turn_id);

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_session
                    ON events(session_id, event_id);

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    request_id TEXT,
                    kind TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decision TEXT,
                    fingerprint TEXT,
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at);

                CREATE TABLE IF NOT EXISTS handoffs (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    from_agent_id TEXT NOT NULL,
                    to_agent_id TEXT NOT NULL,
                    parent_run_id TEXT,
                    child_run_id TEXT,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL,
                    require_approval INTEGER NOT NULL,
                    approval_id TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_handoffs_request ON handoffs(request_id);
                CREATE INDEX IF NOT EXISTS idx_handoffs_parent ON handoffs(parent_run_id);

                CREATE TABLE IF NOT EXISTS process_lease (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    owner_pid INTEGER NOT NULL,
                    started_at REAL NOT NULL,
                    source_file TEXT NOT NULL DEFAULT ''
                );
            """)
            current = 2
        if current < 3:
            conn.execute("CREATE TABLE IF NOT EXISTS event_retention ("
                         "session_id TEXT PRIMARY KEY, discarded_through INTEGER NOT NULL)")
            # Version 2 did not record which session lost an event. Retained
            # global IDs give a conservative boundary for that legacy history.
            first = conn.execute("SELECT MIN(event_id) FROM events").fetchone()[0]
            if first and first > 1:
                conn.execute("INSERT OR IGNORE INTO event_retention VALUES ('*', ?)", (first - 1,))
            current = 3
        if current < 4:
            conn.execute("CREATE TABLE IF NOT EXISTS background_deliveries ("
                         "delivery_key TEXT PRIMARY KEY, digest TEXT NOT NULL, receipt_json TEXT NOT NULL)")
            current = 4
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(current),),
        )

    def schema_version(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
            return int(row["value"]) if row else 1

    def backup(self, dest: Path | str) -> Path:
        """Copy a consistent snapshot. Caller owns retention of dest."""
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists():
            dest_path.unlink()
        with self._get_conn() as conn:
            conn.execute("VACUUM INTO ?", (str(dest_path),))
        return dest_path

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
                meta = _row_meta(r["metadata_json"])
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

    def recover_interrupted_sessions(self) -> int:
        """A new gateway cannot attest completion of work its predecessor sent."""
        now = time.time()
        with self._immediate() as conn:
            changed = conn.execute(
                "UPDATE sessions SET status='execution_unknown', updated_at=? WHERE status IN ('running', 'cancelling')",
                (now,),
            )
            conn.execute(
                "UPDATE client_requests SET status='execution_unknown', updated_at=? "
                "WHERE status IN ('admitted', 'running', 'cancelling', 'awaiting_approval')",
                (now,),
            )
            conn.execute(
                "UPDATE handoffs SET status='execution_unknown', updated_at=? "
                "WHERE status IN ('running', 'approved', 'admitted')",
                (now,),
            )
            return changed.rowcount

    def claim_process(self, pid: int | None = None, *, source_file: str = "") -> dict[str, Any]:
        """Exclusive owner for this store. A live foreign pid is not stolen."""
        pid = int(pid or os.getpid())
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute("SELECT * FROM process_lease WHERE id=1").fetchone()
            if row is not None:
                existing = int(row["owner_pid"])
                if existing != pid and pid_is_alive(existing):
                    return {
                        "ok": False,
                        "owned": False,
                        "owner_pid": existing,
                        "self_pid": pid,
                        "error": "store is owned by a live gateway process",
                    }
            conn.execute(
                "INSERT INTO process_lease(id, owner_pid, started_at, source_file) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET owner_pid=excluded.owner_pid, "
                "started_at=excluded.started_at, source_file=excluded.source_file",
                (pid, now, source_file),
            )
            return {"ok": True, "owned": True, "owner_pid": pid, "started_at": now}

    def release_process(self, pid: int | None = None) -> bool:
        pid = int(pid or os.getpid())
        with self._immediate() as conn:
            changed = conn.execute(
                "DELETE FROM process_lease WHERE id=1 AND owner_pid=?", (pid,)
            )
            return changed.rowcount > 0

    def process_lease(self) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM process_lease WHERE id=1").fetchone()
            if not row:
                return None
            return {
                "owner_pid": row["owner_pid"],
                "started_at": row["started_at"],
                "source_file": row["source_file"],
                "alive": pid_is_alive(int(row["owner_pid"])),
            }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            messages = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC, id ASC",
                (session_id,),
            ).fetchall()
            meta = _row_meta(row["metadata_json"])
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
                existing = conn.execute(
                    "SELECT metadata_json FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if existing:
                    prior = _row_meta(existing["metadata_json"])
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
        conn: sqlite3.Connection | None = None,
    ) -> int:
        now = timestamp or time.time()
        tool_str = json.dumps(tool_calls or [])

        def _write(db: sqlite3.Connection) -> int:
            cursor = db.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp, tool_calls_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, now, tool_str),
            )
            db.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return cursor.lastrowid or 0

        if conn is not None:
            return _write(conn)
        with self._get_conn() as owned:
            return _write(owned)

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

    def _request_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "session_id": row["session_id"],
            "digest": row["digest"],
            "turn_id": row["turn_id"],
            "native_run_id": row["native_run_id"],
            "native_session": row["native_session"],
            "status": row["status"],
            "input_text": row["input_text"],
            "result": json.loads(row["result_json"] or "{}"),
            "owner_pid": row["owner_pid"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(row) if row else None

    def get_request_by_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE turn_id=?", (turn_id,)
            ).fetchone()
            return self._request_row(row) if row else None

    def admit_request(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically accept a client request. Identical retries replay.

        Returns a dict with ``replayed`` True when an existing execution is
        returned. Raises RequestConflict / RequestBusy on illegal reuse.
        """
        if not str(text or "").strip():
            raise ValueError("Missing turn text")
        text = str(text).strip()
        rid = str(request_id or uuid.uuid4().hex)
        if not rid or len(rid) > REQUEST_ID_MAX:
            raise ValueError("Invalid request_id")
        digest = input_fingerprint(text, extra=extra)
        now = time.time()
        pid = os.getpid()
        with self._immediate() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, title, profile, workspace, created_at, updated_at, status, metadata_json)
                VALUES (?, 'New Conversation', 'jaeger', '', ?, ?, 'idle', '{}')
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, now, now),
            )
            existing = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (rid,)
            ).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise RequestConflict(
                        "Request identity was already used for different input"
                    )
                payload = self._request_row(existing)
                payload["replayed"] = True
                payload["accepted"] = False
                return payload
            session = conn.execute(
                "SELECT status FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            status = session["status"] if session else "idle"
            if status in {"running", "execution_unknown", "cancelling"}:
                raise RequestBusy(
                    "Previous execution needs reconciliation before another turn"
                    if status == "execution_unknown"
                    else "Turn already in progress"
                )
            turn_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO client_requests (
                    request_id, session_id, digest, turn_id, native_run_id, native_session,
                    status, input_text, result_json, owner_pid, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, NULL, 'admitted', ?, '{}', ?, ?, ?)
                """,
                (rid, session_id, digest, turn_id, text, pid, now, now),
            )
            msg_id = self.append_message(session_id, "user", text, timestamp=now, conn=conn)
            conn.execute(
                "UPDATE sessions SET status='running', updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            event = self._insert_event(
                conn,
                session_id,
                "turn.start",
                {"turn_id": turn_id, "request_id": rid, "message_id": msg_id, "text": text},
                now,
            )
            return {
                "request_id": rid,
                "session_id": session_id,
                "digest": digest,
                "turn_id": turn_id,
                "native_run_id": None,
                "native_session": None,
                "status": "admitted",
                "input_text": text,
                "result": {},
                "owner_pid": pid,
                "created_at": now,
                "updated_at": now,
                "message_id": msg_id,
                "event": event,
                "replayed": False,
                "accepted": True,
            }

    def bind_native(
        self,
        request_id: str,
        *,
        native_run_id: str,
        native_session: str,
        status: str = "running",
    ) -> dict[str, Any] | None:
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                return None
            if row["status"] in {"completed", "failed", "cancelled"}:
                return self._request_row(row)
            conn.execute(
                "UPDATE client_requests SET native_run_id=?, native_session=?, status=?, "
                "updated_at=? WHERE request_id=?",
                (native_run_id, native_session, status, now, request_id),
            )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(updated) if updated else None

    def complete_request(
        self,
        request_id: str,
        *,
        status: str,
        result: dict[str, Any],
        assistant_text: str | None = None,
        session_status: str | None = None,
        event_name: str | None = None,
    ) -> dict[str, Any]:
        """Commit result, transcript and terminal event together, once."""
        event_name = event_name or {
            "completed": "turn.finish", "failed": "turn.failed",
            "cancelled": "turn.cancelled", "execution_unknown": "turn.unknown",
        }[status]
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown request {request_id}")
            if row["status"] in {"completed", "failed", "cancelled"}:
                payload = self._request_row(row)
                payload["replayed"] = True
                return payload
            conn.execute(
                "UPDATE client_requests SET status=?, result_json=?, updated_at=? WHERE request_id=?",
                (status, json.dumps(result), now, request_id),
            )
            if assistant_text is not None:
                self.append_message(row["session_id"], "assistant", assistant_text, timestamp=now, conn=conn)
            sess_status = session_status or ("idle" if status == "completed" else status)
            conn.execute(
                "UPDATE sessions SET status=?, updated_at=? WHERE session_id=?",
                (sess_status, now, row["session_id"]),
            )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            payload = self._request_row(updated)
            payload["replayed"] = False
            payload["event"] = self._insert_event(
                conn, row["session_id"], event_name,
                {**result, "request_id": request_id, "turn_id": row["turn_id"], "status": status}, now,
            )
            return payload

    def mark_request_status(self, request_id: str, status: str) -> dict[str, Any] | None:
        now = time.time()
        with self._immediate() as conn:
            changed = conn.execute(
                "UPDATE client_requests SET status=?, updated_at=? WHERE request_id=? "
                "AND status NOT IN ('completed', 'failed', 'cancelled')",
                (status, now, request_id),
            )
            if changed.rowcount == 0:
                row = conn.execute(
                    "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
                ).fetchone()
                return self._request_row(row) if row else None
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(row) if row else None

    def _insert_event(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        event: str,
        data: dict[str, Any],
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        now = timestamp or time.time()
        cursor = conn.execute(
            "INSERT INTO events(session_id, event, data_json, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, event, json.dumps(data), now),
        )
        event_id = int(cursor.lastrowid or 0)
        overflow = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"] - MAX_RETAINED_EVENTS
        if overflow > 0:
            conn.execute(
                "INSERT INTO event_retention(session_id, discarded_through) "
                "SELECT session_id, MAX(event_id) FROM "
                "(SELECT session_id, event_id FROM events ORDER BY event_id LIMIT ?) "
                "GROUP BY session_id "
                "ON CONFLICT(session_id) DO UPDATE SET discarded_through="
                "MAX(discarded_through, excluded.discarded_through)", (overflow,),
            )
            conn.execute(
                "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events ORDER BY event_id ASC LIMIT ?)",
                (overflow,),
            )
        return {
            "event_id": event_id,
            "session_id": session_id,
            "event": event,
            "data": data,
            "timestamp": now,
        }

    def receive_background(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Durable inbox: one transcript message + event per native delivery.

        Receipt survives event retention and session deletion. An ACK lost in
        transit must not resurrect a deleted conversation or append twice.
        """
        required = ("delivery_id", "profile", "agent_id", "display_name", "source",
                    "source_session", "status", "text", "session_id")
        if any(not isinstance(payload.get(k), str) or not payload[k] for k in required):
            raise ValueError("Invalid native background delivery")
        if payload["session_id"] != "dispatcher" or payload["agent_id"] != "native:" + payload["profile"]:
            raise ValueError("Background delivery must name its native dispatcher")
        if payload["status"] not in {"completed", "failed", "cancelled", "execution_unknown"}:
            raise ValueError("Invalid background result status")
        # Default instance uses the canonical conversation; other native
        # instances cannot overwrite it with their own messages.
        session = "dispatcher" if payload["profile"] == "jaeger" else "dispatcher:" + payload["profile"]
        key = json.dumps([payload["profile"], payload["delivery_id"]])
        digest = input_fingerprint(payload["text"], extra=payload)
        now = time.time()
        with self._immediate() as conn:
            old = conn.execute("SELECT digest, receipt_json FROM background_deliveries WHERE delivery_key=?", (key,)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise RequestConflict("Background delivery identity reused with different contents")
                return {**json.loads(old["receipt_json"]), "replayed": True}
            existing = conn.execute("SELECT profile FROM sessions WHERE session_id=?", (session,)).fetchone()
            if existing and existing["profile"] != payload["profile"]:
                raise RequestConflict("Background destination belongs to a different profile")
            conn.execute(
                "INSERT OR IGNORE INTO sessions(session_id,title,profile,created_at,updated_at,metadata_json) "
                "VALUES(?,?,?,?,?,?)", (session, payload["display_name"], payload["profile"], now, now,
                                        json.dumps({"agent_id": payload["agent_id"], "native_session": "dispatcher"})))
            cursor = conn.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES(?,'assistant',?,?)",
                                  (session, payload["text"], now))
            conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session))
            event = self._insert_event(conn, session, "message.created", {
                **payload, "session_id": session, "native_session": "dispatcher",
                "message_id": cursor.lastrowid, "role": "assistant", "initiated_by": "agent"}, now)
            receipt = {"delivery_id": payload["delivery_id"], "session_id": session,
                       "message_id": cursor.lastrowid, "event": event}
            conn.execute("INSERT INTO background_deliveries VALUES(?,?,?)", (key, digest, json.dumps(receipt)))
            return {**receipt, "replayed": False}

    def append_event(self, session_id: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._immediate() as conn:
            return self._insert_event(conn, session_id, event, data)

    def replay_events(
        self,
        session_id: str,
        since_event_id: int = 0,
        *,
        limit: int = 500,
    ) -> dict[str, Any]:
        with self._get_conn() as conn:
            bounds = conn.execute(
                "SELECT MIN(event_id) AS lo, MAX(event_id) AS hi FROM events WHERE session_id IN (?, '*')",
                (session_id,),
            ).fetchone()
            lo, hi = bounds["lo"], bounds["hi"]
            discarded = conn.execute(
                "SELECT MAX(discarded_through) FROM event_retention WHERE session_id IN (?, '*')",
                (session_id,),
            ).fetchone()[0]
            cursor_expired = bool(since_event_id > 0 and discarded and since_event_id < discarded)
            rows = conn.execute(
                "SELECT * FROM events WHERE session_id IN (?, '*') AND event_id > ? "
                "ORDER BY event_id ASC LIMIT ?",
                (session_id, since_event_id, max(1, min(limit, MAX_RETAINED_EVENTS))),
            ).fetchall()
            events = [
                {
                    "event_id": r["event_id"],
                    "session_id": r["session_id"],
                    "event": r["event"],
                    "data": json.loads(r["data_json"] or "{}"),
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]
            return {
                "events": events,
                "cursor_expired": cursor_expired,
                "oldest_event_id": lo,
                "latest_event_id": hi,
                "valid_cursor": not cursor_expired,
            }

    def create_approval(
        self,
        *,
        kind: str,
        prompt: str,
        options: list[str],
        session_id: str | None = None,
        request_id: str | None = None,
        fingerprint: str | None = None,
        metadata: dict[str, Any] | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        aid = approval_id or f"approval_{uuid.uuid4().hex[:12]}"
        with self._immediate() as conn:
            conn.execute(
                """
                INSERT INTO approvals(
                    approval_id, session_id, request_id, kind, prompt, options_json,
                    status, decision, fingerprint, created_at, resolved_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?, NULL, ?)
                """,
                (
                    aid,
                    session_id,
                    request_id,
                    kind,
                    prompt,
                    json.dumps(list(options)),
                    fingerprint,
                    now,
                    json.dumps(metadata or {}),
                ),
            )
        return self.get_approval(aid) or {}

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            return self._approval_row(row) if row else None

    def _approval_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "approval_id": row["approval_id"],
            "session_id": row["session_id"],
            "request_id": row["request_id"],
            "kind": row["kind"],
            "prompt": row["prompt"],
            "options": json.loads(row["options_json"] or "[]"),
            "status": row["status"],
            "decision": row["decision"],
            "fingerprint": row["fingerprint"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
            "metadata": _row_meta(row["metadata_json"]),
        }

    def resolve_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        decision: str | None = None,
    ) -> dict[str, Any] | None:
        """First writer wins. Duplicate or stale ids return None."""
        now = time.time()
        choice = decision or ("once" if approved else "deny")
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            if row is None or row["status"] != "pending":
                return None
            conn.execute(
                "UPDATE approvals SET status='resolved', decision=?, resolved_at=? WHERE approval_id=?",
                (choice, now, approval_id),
            )
            updated = conn.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            return self._approval_row(updated) if updated else None

    def wait_for_approval(self, approval_id: str, *, timeout_s: float = 120.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            row = self.get_approval(approval_id)
            if row is None:
                return {"approval_id": approval_id, "status": "missing", "decision": "deny"}
            if row["status"] == "resolved":
                return row
            time.sleep(0.05)
        self.resolve_approval(approval_id, approved=False, decision="deny")
        return self.get_approval(approval_id) or {
            "approval_id": approval_id,
            "status": "resolved",
            "decision": "deny",
        }

    def save_handoff(self, record: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._immediate() as conn:
            prior = conn.execute("SELECT * FROM handoffs WHERE id=?", (record["id"],)).fetchone()
            if prior and prior["status"] in {"completed", "failed", "cancelled", "denied"}:
                return self._handoff_row(prior)
            conn.execute(
                """
                INSERT INTO handoffs(
                    id, request_id, from_agent_id, to_agent_id, parent_run_id, child_run_id,
                    task, status, require_approval, approval_id, result_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    child_run_id=excluded.child_run_id,
                    result_json=excluded.result_json,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record["id"],
                    record.get("request_id") or record["id"],
                    record["from_agent_id"],
                    record["to_agent_id"],
                    record.get("parent_run_id"),
                    record.get("child_run_id"),
                    record["task"],
                    record["status"],
                    1 if record.get("require_approval") else 0,
                    record.get("approval_id"),
                    json.dumps(record.get("result") or record.get("result_json") or {}),
                    json.dumps(record.get("metadata") or {}),
                    record.get("created_at") or now,
                    now,
                ),
            )
        return self.get_handoff(record["id"]) or record

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM handoffs WHERE id=?", (handoff_id,)).fetchone()
            return self._handoff_row(row) if row else None

    def get_handoff_by_request(self, request_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM handoffs WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._handoff_row(row) if row else None

    def list_handoffs(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM handoffs ORDER BY created_at DESC"
            ).fetchall()
            return [self._handoff_row(r) for r in rows]

    def count_active_handoffs(self, *, parent_run_id: str | None = None) -> int:
        with self._get_conn() as conn:
            if parent_run_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM handoffs WHERE parent_run_id=? "
                    "AND status IN ('pending_approval', 'approved', 'running', 'admitted')",
                    (parent_run_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM handoffs "
                    "WHERE status IN ('pending_approval', 'approved', 'running', 'admitted')"
                ).fetchone()
            return int(row["n"] if row else 0)

    def _handoff_row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = json.loads(row["result_json"] or "{}")
        meta = _row_meta(row["metadata_json"])
        return {
            "id": row["id"],
            "request_id": row["request_id"],
            "from_agent_id": row["from_agent_id"],
            "to_agent_id": row["to_agent_id"],
            "parent_run_id": row["parent_run_id"],
            "child_run_id": row["child_run_id"],
            "task": row["task"],
            "status": row["status"],
            "require_approval": bool(row["require_approval"]),
            "approval_id": row["approval_id"],
            "result": result,
            "result_summary": result.get("summary"),
            "metadata": meta,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
