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
import threading
from typing import Any, Callable, Iterator


SCHEMA_VERSION = 15
MAX_RETAINED_EVENTS = 5000
REQUEST_ID_MAX = 128
MAX_QUEUE_PER_SESSION = 100
QUEUE_STATUSES = frozenset({'queued', 'paused'})


class RequestConflict(ValueError):
    """A client request_id was reused with a different input fingerprint."""


class RequestBusy(RuntimeError):
    """A session already has in-flight or unreconciliation work."""


def default_store_path(*, create: bool = True) -> Path:
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
    if create:root.mkdir(parents=True, exist_ok=True)
    return root / "gateway_sessions.sqlite3"


def input_fingerprint(text: str, *, extra: dict[str, Any] | None = None) -> str:
    payload = {"text": text, **(extra or {})}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


#: Client-supplied turn fields that change what an admitted request executes.
#: A retry must carry the same values to replay; different values under the
#: same request_id are a conflict, never a silent re-selection.
EXECUTION_INPUT_KEYS = (
    "model", "provider", "attachment_ids", "workspace", "options",
    "allowed_tools", "display_text", "is_subordinate", "interaction_tier",
    # Assigned by the Gateway from the authenticated caller, never by a client.
    "caller",
)
#: Version 1 digests covered text only (pre-2026-09-22 receipts). Version 2
#: covers text plus every explicit ``EXECUTION_INPUT_KEYS`` value.
REQUEST_FINGERPRINT_VERSION = 2


def request_fingerprint(text: str, requested: dict[str, Any] | None = None) -> str:
    """Versioned digest of everything the client asked this request to run."""
    return input_fingerprint(
        text, extra={"_fingerprint": REQUEST_FINGERPRINT_VERSION, "request": requested or {}},
    )


def _normalize_requested(requested: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only explicit execution choices, in canonical types.

    Absent and blank values are omitted so ``{"model": ""}`` and ``{}``
    are the same request (both mean "use the session default").
    """
    out: dict[str, Any] = {}
    for key in EXECUTION_INPUT_KEYS:
        value = (requested or {}).get(key)
        if value is None:
            continue
        if key == "attachment_ids":
            if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
                raise ValueError("attachment_ids must be a list of strings")
            out[key] = [v for v in value]
        elif key == "allowed_tools":
            # A host tool grant. [] is meaningful — no tools at all — and is
            # never widened to "unrestricted" (absent).
            if not isinstance(value, (list, tuple)) or not all(
                    isinstance(v, str) and v.strip() for v in value):
                raise ValueError("allowed_tools must be a list of nonempty tool names")
            out[key] = sorted({v.strip() for v in value})
        elif key == "display_text":
            # Visible user text. Empty is distinct from omitted: omitted
            # means persist the execution prompt; empty means persist "".
            out[key] = str(value)
        elif key == "is_subordinate":
            # False/omitted are the same request (primary turn). True is
            # an explicit subordinate grant and must replay identically.
            if value in (True, "true", "1", 1):
                out[key] = True
        elif key == "options":
            if not isinstance(value, dict):
                raise ValueError("options must be an object")
            if value:
                out[key] = value
        elif key == "interaction_tier":
            tier_val = str(value).strip().lower()
            if tier_val in ("chat", "agent", "jaeger"):
                out[key] = tier_val
            elif tier_val:
                raise ValueError(f"interaction_tier must be one of ['chat', 'agent', 'jaeger'], got '{tier_val}'")
        else:
            text = str(value).strip()
            if text:
                out[key] = text
    return out


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


MESSAGE_KINDS = frozenset({"message", "channel_message", "summary", "handoff_request", "handoff_result", "task_result"})
MESSAGES_PAGE_MAX = 200


def _attachment_parts(conn: Any, session_id: str, execution: dict[str, Any]) -> list[dict[str, Any]] | None:
    """``{type:"attachment", attachment_id, name, mime, size}`` for each attachment
    a turn's admission snapshot selected, so the user message shows them on reload."""
    ids = [str(a.get("attachment_id")) for a in (execution.get("attachments") or [])
           if isinstance(a, dict) and a.get("attachment_id")]
    if not ids:
        return None
    rows = {r["attachment_id"]: r for r in conn.execute(
        f"SELECT attachment_id, original_filename, mime_type, size_bytes FROM attachments "
        f"WHERE session_id=? AND attachment_id IN ({','.join('?' * len(ids))})",
        (session_id, *ids),
    ).fetchall()}
    return [{"type": "attachment", "attachment_id": a,
             "name": rows[a]["original_filename"] if a in rows else None,
             "mime": rows[a]["mime_type"] if a in rows else None,
             "size": rows[a]["size_bytes"] if a in rows else None} for a in ids]


def _part_view(part: Any) -> Any:
    """Tool parts carry ``state`` (the contract name) next to the stored ``status``."""
    if isinstance(part, dict) and part.get("type") in {"tool", "approval"} and "state" not in part:
        return {**part, "state": part.get("status")}
    return part


def _channel_message_view(extra: dict[str, Any]) -> dict[str, str]:
    return {key: extra[key] for key in ('channel_id','provider_conversation_id','external_message_id','ingress_author_id','authority') if isinstance(extra.get(key),str)}


def message_dict(m: Any, session_id: str | None = None) -> dict[str, Any]:
    """One transcript row in the sessions-contract shape (plus the legacy keys)."""
    keys = m.keys() if hasattr(m, "keys") else []
    get = (lambda k, d=None: m[k] if k in keys else d)
    links = _row_meta(get("links_json"))
    extra = _row_meta(get("meta_json"))
    parts = json.loads(get("parts_json")) if get("parts_json") else []
    out: dict[str, Any] = {
        "id": get("id"),
        "session_id": get("session_id") or session_id,
        "role": get("role"),
        "kind": get("kind") or "message",
        "sender_agent_id": get("sender_agent_id"),
        "created_at": get("timestamp"),
        "timestamp": get("timestamp"),
        "content": get("content") or "",
        "parts": [_part_view(p) for p in parts],
        "tool_calls": json.loads(get("tool_calls_json") or "[]"),
        "links": links,
    }
    if isinstance(extra.get("status"), str):
        out["status"] = extra["status"]
    for key in ("request_id", "turn_id"):
        if isinstance(extra.get(key), str):
            out[key] = extra[key]
    if out["kind"] == "channel_message":
        out["channel"] = _channel_message_view(extra)
    if out["kind"] == "summary" and isinstance(extra.get("summary"), dict):
        out["summary"] = extra["summary"]
    return out


def _typed_fields(m: Any) -> dict[str, Any]:
    """Contract fields added to the legacy message rows only when set, so
    plain chat rows keep their established shape."""
    keys = m.keys()
    out: dict[str, Any] = {}
    extra = _row_meta(m["meta_json"] if "meta_json" in keys else None)
    for key in ("request_id", "turn_id"):
        if isinstance(extra.get(key), str):
            out[key] = extra[key]
    kind = m["kind"] if "kind" in keys else None
    if kind and kind != "message":
        out["kind"] = kind
        extra = _row_meta(m["meta_json"])
        if isinstance(extra.get("status"), str):
            out["status"] = extra["status"]
        if kind == "channel_message":
            out["channel"] = _channel_message_view(extra)
        if kind == "summary" and isinstance(extra.get("summary"), dict):
            out["summary"] = extra["summary"]
    if "sender_agent_id" in keys and m["sender_agent_id"]:
        out["sender_agent_id"] = m["sender_agent_id"]
    if "links_json" in keys and m["links_json"]:
        out["links"] = _row_meta(m["links_json"])
    return out


def _session_agent(session_id: str, meta: dict[str, Any]) -> str | None:
    """The agent a session belongs to. A specialist's worker session is created
    by its first turn, without metadata, so its id names the agent."""
    if meta.get("agent_id"):
        return meta["agent_id"]
    from jaeger_ai.core.agent_registry.specialist_runtime import specialist_agent
    return specialist_agent(session_id)


LIST_PREVIEW_CHARS = 140


def _list_preview(content: Any) -> str | None:
    if content is None:
        return None
    text = " ".join(str(content).split())
    return text if len(text) <= LIST_PREVIEW_CHARS else text[: LIST_PREVIEW_CHARS - 1] + "\u2026"


class GatewaySessionStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        #: Called with each event record the store writes itself (message.created),
        #: after its transaction commits. The event bus attaches its fanout here.
        self.event_listener: Callable[[dict[str, Any]], Any] | None = None
        self._pending_events = threading.local()
        self._init_db()

    def _queue_event(self, record: dict[str, Any]) -> None:
        pending = getattr(self._pending_events, "items", None)
        if pending is None:
            pending = self._pending_events.items = []
        pending.append(record)

    def _flush_events(self) -> None:
        pending = getattr(self._pending_events, "items", None) or []
        self._pending_events.items = []
        listener = self.event_listener
        for record in pending:
            if listener is not None:
                try:
                    listener(record)
                except Exception:  # noqa: BLE001 — a wake-up must never fail a write
                    pass

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
            self._pending_events.items = []
            raise
        finally:
            conn.close()
        self._flush_events()

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
            conn.execute("CREATE TABLE IF NOT EXISTS control_operations (operation_id TEXT PRIMARY KEY, "
                         "fingerprint TEXT NOT NULL, status TEXT NOT NULL, receipt_json TEXT, created_at REAL NOT NULL)")
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
        if current < 5:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS attachments (
                    attachment_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    safe_path TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT,
                    provenance TEXT NOT NULL DEFAULT 'remote_upload',
                    created_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_attachments_session
                    ON attachments(session_id, created_at);
            """)
            current = 5
        if current < 6:
            # Admission snapshot (R01): the resolved model/provider/attachments
            # an admitted request executes with, frozen at admission, and the
            # digest schema its identity was computed under. Existing rows
            # stay digest_version 1 with an empty snapshot; they replay by
            # their original text-only digest and are never reinterpreted.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(client_requests)")}
            if "execution_json" not in columns:
                conn.execute("ALTER TABLE client_requests ADD COLUMN execution_json TEXT NOT NULL DEFAULT '{}'")
            if "digest_version" not in columns:
                conn.execute("ALTER TABLE client_requests ADD COLUMN digest_version INTEGER NOT NULL DEFAULT 1")
            current = 6
        if current < 7:
            conn.execute("CREATE TABLE IF NOT EXISTS activity_history (event_id INTEGER PRIMARY KEY, "
                         "session_id TEXT NOT NULL, event TEXT NOT NULL, "
                         "data_json TEXT NOT NULL, timestamp REAL NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_session ON activity_history(session_id, event_id)")
            conn.execute("INSERT OR IGNORE INTO activity_history SELECT * FROM events WHERE session_id != '*' ")
            current = 7
        if current < 8:
            # Gateway-owned session queue. A queued item is still a
            # client_request: one durable identity, one execution snapshot,
            # and one terminal receipt. No client owns a second queue.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(client_requests)")}
            if "queue_position" not in columns:
                conn.execute("ALTER TABLE client_requests ADD COLUMN queue_position INTEGER NOT NULL DEFAULT 0")
            current = 8
        if current < 9:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(client_requests)")}
            if "requested_json" not in columns:
                conn.execute("ALTER TABLE client_requests ADD COLUMN requested_json TEXT NOT NULL DEFAULT '{}'")
            current = 9
        if current < 10:
            # Handoffs carry the chat session they were started from, so the
            # Agents View can place and filter markers without a join per row.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(handoffs)")}
            if "session_id" not in columns:
                conn.execute("ALTER TABLE handoffs ADD COLUMN session_id TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_handoffs_session ON handoffs(session_id)")
            current = 10
        if current < 11:
            # Response parts (reasoning/text/tool/plan), projected from the
            # turn's events at completion. NULL for older rows and user turns.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
            if "parts_json" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN parts_json TEXT")
            current = 11
        if current < 12:
            # Sessions contract: typed messages (summary / handoff_request /
            # handoff_result / task_result), who sent them, and links to the
            # handoff/task/child session they report on.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
            for col, ddl in (("kind", "TEXT NOT NULL DEFAULT 'message'"), ("sender_agent_id", "TEXT"),
                             ("links_json", "TEXT"), ("meta_json", "TEXT")):
                if col not in columns:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {ddl}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id)")
            current = 12
        if current < 13:
            from jaeger_ai.features.agent_bridge.service import migrate
            migrate(conn)
            current = 13
        if current < 14:
            from jaeger_ai.features.agent_bridge.outbox import migrate as migrate_outbox
            migrate_outbox(conn)
            current = 14
        if current < 15:
            if "source_message_id" not in {row["name"] for row in conn.execute("PRAGMA table_info(agent_goals)")}:
                conn.execute("ALTER TABLE agent_goals ADD COLUMN source_message_id TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS agent_goal_source ON agent_goals(caller,source_message_id) WHERE source_message_id IS NOT NULL")
            current = 15
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

    def list_sessions(self, profile: str | None = None, query: str | None = None,
                      agent_id: str | None = None) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            sql = (
                "SELECT s.*, COUNT(m.id) as message_count, MAX(m.timestamp) AS last_message_at, "
                "(SELECT lm.content FROM messages lm WHERE lm.session_id = s.session_id "
                " ORDER BY lm.timestamp DESC, lm.id DESC LIMIT 1) AS last_content, "
                "(SELECT MAX(e.event_id) FROM events e WHERE e.session_id = s.session_id) AS last_event_id "
                "FROM sessions s LEFT JOIN messages m ON s.session_id = m.session_id"
            )
            params: list[Any] = []
            clauses = []
            if profile:
                clauses.append("s.profile = ?")
                params.append(profile)
            if agent_id:
                from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
                prefix = specialist_session(agent_id, "")
                clauses.append("(json_extract(s.metadata_json, '$.agent_id') = ? "
                               "OR (json_extract(s.metadata_json, '$.agent_id') IS NULL "
                               "AND substr(s.session_id, 1, ?) = ?))")
                params.extend([agent_id, len(prefix), prefix])
            term = str(query or "").strip()
            if term:
                like = f"%{term}%"
                clauses.append("(s.title LIKE ? OR s.workspace LIKE ? OR s.session_id LIKE ? OR EXISTS (SELECT 1 FROM messages sm WHERE sm.session_id = s.session_id AND sm.content LIKE ?))")
                params.extend([like, like, like, like])
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " GROUP BY s.session_id ORDER BY s.updated_at DESC"
            rows = conn.execute(sql, params).fetchall()
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
                    "agent_id": _session_agent(r["session_id"], meta),
                    # Sidebar row without N follow-up reads (Agents View).
                    "last_message_preview": _list_preview(r["last_content"]),
                    "last_activity_at": max(float(r["updated_at"] or 0), float(r["last_message_at"] or 0)),
                    "last_event_id": r["last_event_id"],
                }
                if term:
                    row["search_match"] = True
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

    def get_session(self, session_id: str, *, conversation: bool = False) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            if conversation:
                conn.execute("BEGIN")  # one read snapshot: transcript, receipt and replay cursor
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if not row:
                return None
            messages = conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC, id ASC",
                (session_id,),
            ).fetchall()
            meta = _row_meta(row["metadata_json"])
            payload = {
                "session_id": row["session_id"],
                "title": row["title"],
                "profile": row["profile"],
                "workspace": row["workspace"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "metadata": meta,
                "agent_id": _session_agent(row["session_id"], meta),
                "messages": [
                    {
                        "id": m["id"],
                        "role": m["role"],
                        "content": m["content"],
                        "timestamp": m["timestamp"],
                        "tool_calls": json.loads(m["tool_calls_json"] or "[]"),
                        **({"parts": json.loads(m["parts_json"])} if m["parts_json"] else {}),
                        **_typed_fields(m),
                    }
                    for m in messages
                ],
            }

            if conversation:
                request_row = conn.execute(
                    "SELECT * FROM client_requests WHERE session_id=? "
                    "AND status NOT IN ('queued', 'paused') ORDER BY created_at DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                latest = self._request_row(request_row) if request_row else None
                payload["latest_request"] = ({key: latest.get(key) for key in (
                    "session_id", "request_id", "turn_id", "status", "updated_at", "finished_at",
                )} if latest else None)
                if latest and isinstance(latest.get("result", {}).get("error"), str):
                    payload["latest_request"]["error"] = latest["result"]["error"][:4096]
                payload["event_cursor"] = conn.execute(
                    "SELECT COALESCE(MAX(event_id), 0) FROM events WHERE session_id IN (?, '*')",
                    (session_id,),
                ).fetchone()[0]
                partial = []
                # A terminal assistant message already contains the final text.
                has_answer = latest and any(
                    m["role"] == "assistant" and m["timestamp"] >= latest["created_at"]
                    for m in messages
                )
                if latest and not has_answer:
                    for event in conn.execute(
                        "SELECT data_json FROM activity_history WHERE session_id=? AND event='turn.delta' ORDER BY event_id",
                        (session_id,),
                    ):
                        data = json.loads(event["data_json"] or "{}")
                        if data.get("request_id") == latest["request_id"] and isinstance(data.get("delta"), str):
                            partial.append(data["delta"])
                payload["partial_text"] = "".join(partial)
                context = []
                if latest:
                    for event in conn.execute(
                        "SELECT event, data_json FROM activity_history WHERE session_id=? "
                        "AND (event LIKE 'tool.%' OR event='agent.handoff' OR event LIKE 'agent.handoff.%') ORDER BY event_id",
                        (session_id,),
                    ):
                        data = json.loads(event["data_json"] or "{}")
                        if data.get("request_id") == latest["request_id"]:
                            # Handoff events carry their record under `handoff`.
                            # Project identity/status only; never expose tool arguments or worker output here.
                            detail = data.get("handoff") if isinstance(data.get("handoff"), dict) else data
                            context.append({"event": event["event"], **{
                                key: detail[key] for key in ("tool", "text", "phase", "status", "child_run_id", "task_id", "parent_run_id", "from_agent_id", "to_agent_id")
                                if isinstance(detail.get(key), str)
                            }})
                payload["activity_context"] = context[-50:]
            return payload

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

    def branch_session(self, session_id: str, *, title: str | None = None,
                       keep_count: int | None = None) -> dict[str, Any] | None:
        """Create an independent Gateway-owned copy of a conversation."""
        source = self.get_session(session_id)
        if source is None:
            return None
        messages = list(source.get("messages") or [])
        if keep_count is not None:
            messages = messages[:max(0, int(keep_count))]
        branch_id = uuid.uuid4().hex
        metadata = dict(source.get("metadata") or {})
        metadata.update({"source": "fork", "parent_session_id": session_id})
        branch = self.ensure_session(
            branch_id,
            title=(title or f"{source.get('title') or 'Conversation'} (fork)")[:200],
            profile=source.get("profile") or "jaeger",
            workspace=source.get("workspace") or "",
            metadata=metadata,
        )
        for message in messages:
            self.append_message(
                branch_id, str(message.get("role") or "user"),
                str(message.get("content") or ""),
                tool_calls=message.get("tool_calls") or [],
                timestamp=message.get("timestamp"),
                emit=False,
            )
        return self.get_session(branch_id) or branch

    def rename_session(self, session_id: str, title: str) -> dict[str, Any] | None:
        """Set a session's title. The Gateway owns titles; clients project them.

        Returns the updated session, or ``None`` when the session is unknown.
        Does not touch ``updated_at``: a rename is not conversation activity and
        must not reorder the sidebar.
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE sessions SET title = ? WHERE session_id = ?",
                (title, session_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_session(session_id)

    def set_session_archived(self, session_id: str, archived: bool) -> dict[str, Any] | None:
        """Set the Gateway-owned archive flag in session metadata.

        Archive state is session organization, not conversation activity, so it
        does not touch ``updated_at`` or reorder the sidebar.
        """
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            metadata = _row_meta(row["metadata_json"])
            metadata["archived"] = bool(archived)
            conn.execute(
                "UPDATE sessions SET metadata_json = ? WHERE session_id = ?",
                (json.dumps(metadata), session_id),
            )
        return self.get_session(session_id)


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
        parts: list[dict[str, Any]] | None = None,
        kind: str = "message",
        sender_agent_id: str | None = None,
        links: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        emit: bool = True,
    ) -> int:
        """Append one transcript row and, unless ``emit`` is false, publish
        ``message.created {session_id, message}`` on the session and global
        streams once the row's transaction commits."""
        if kind not in MESSAGE_KINDS:
            raise ValueError(f"unknown message kind: {kind!r}")
        now = timestamp or time.time()
        tool_str = json.dumps(tool_calls or [])
        parts_str = json.dumps(parts) if parts else None
        links_str = json.dumps({k: v for k, v in links.items() if v is not None}) if links else None
        meta_str = json.dumps(meta) if meta else None

        def _write(db: sqlite3.Connection) -> int:
            cursor = db.execute(
                """
                INSERT INTO messages (session_id, role, content, timestamp, tool_calls_json, parts_json,
                                      kind, sender_agent_id, links_json, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, role, content, now, tool_str, parts_str, kind, sender_agent_id, links_str, meta_str),
            )
            db.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            msg_id = cursor.lastrowid or 0
            if emit:
                row = db.execute("SELECT * FROM messages WHERE id = ?", (msg_id,)).fetchone()
                payload = {"session_id": session_id, "message": message_dict(row, session_id)}
                self._queue_event(self._insert_event(db, session_id, "message.created", payload, now))
                self._queue_event(self._insert_event(db, "*", "message.created", payload, now))
            return msg_id

        if conn is not None:
            return _write(conn)
        with self._get_conn() as owned:
            msg_id = _write(owned)
        self._flush_events()
        return msg_id

    def list_messages(self, session_id: str, *, before: int | None = None,
                      limit: int = 50) -> dict[str, Any]:
        """Newest first. ``next_before`` pages to older rows; null at the start."""
        limit = max(1, min(int(limit or 50), MESSAGES_PAGE_MAX))
        with self._get_conn() as conn:
            if before is not None:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id=? AND id<? ORDER BY id DESC LIMIT ?",
                    (session_id, int(before), limit + 1)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        return {"messages": [message_dict(r, session_id) for r in rows],
                "next_before": rows[-1]["id"] if more and rows else None}

    def messages_after(self, session_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        """Oldest first, every row with id > ``after_id`` (summarizer input)."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE session_id=? AND id>? ORDER BY id ASC",
                                (session_id, int(after_id or 0))).fetchall()
        return [message_dict(r, session_id) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._get_conn() as conn:
            res = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM activity_history WHERE session_id = ?", (session_id,))
            return res.rowcount > 0

    @staticmethod
    def model_choice_revision(metadata: dict[str, Any]) -> int:
        value=metadata.get('model_choice_revision',0)
        if type(value) is not int or not 0<=value<2**53-1:
            raise ValueError('Stored model-choice generation is invalid; inspect without overwriting')
        return value

    def update_metadata(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Atomic merge; unrelated metadata cannot be lost to a concurrent writer."""
        patch = dict(patch or {})
        if 'model_choice_revision' in patch:raise ValueError('Model-choice generation is owner-managed')
        with self._immediate() as conn:
            row=conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?',(session_id,)).fetchone()
            if row is None:return None
            meta=_row_meta(row['metadata_json'])
            if {'model','provider'} & patch.keys():meta['model_choice_revision']=self.model_choice_revision(meta)+1
            meta.update(patch or {})
            conn.execute('UPDATE sessions SET metadata_json=?,updated_at=? WHERE session_id=?',(json.dumps(meta),time.time(),session_id))
        return self.get_session(session_id)

    @staticmethod
    def _model_choice_fingerprint(session_id, operation_id, expected_revision, actor, requested_model):
        import re
        if not isinstance(operation_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',operation_id):raise ValueError('Valid model operation ID required')
        if type(expected_revision) is not int or not 0<=expected_revision<2**53-1:raise ValueError('Current model-choice generation required')
        if requested_model is not None and (not isinstance(requested_model,str) or not requested_model.strip()):raise ValueError('Invalid requested model')
        command={'domain':'model_choice','session_id':session_id,'requested_model':requested_model,'expected_revision':expected_revision,'actor':actor}
        return input_fingerprint(json.dumps(command,sort_keys=True))

    def model_choice_operation(self, session_id, *, operation_id, expected_revision, actor, requested_model):
        fingerprint=self._model_choice_fingerprint(session_id,operation_id,expected_revision,actor,requested_model)
        with self._get_conn() as conn:
            prior=conn.execute('SELECT fingerprint,receipt_json FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
        if prior is None:return None
        if prior['fingerprint']!=fingerprint:raise ValueError('Model operation ID belongs to another command')
        if prior['receipt_json'] is None:raise ValueError('Earlier model operation unresolved; inspect without replay')
        return json.loads(prior['receipt_json'])

    def cancel_model_choice(self, session_id, *, operation_id, expected_revision, actor, requested_model):
        """Resolve an uncertain config intent without undoing any committed choice.

        A receipt already committed wins. Otherwise the original command receives
        a rejection atomically, so an in-flight/late handler cannot apply it.
        This affects no turn/request, tool, permission or model execution.
        """
        fingerprint=self._model_choice_fingerprint(session_id,operation_id,expected_revision,actor,requested_model)
        with self._immediate() as conn:
            prior=conn.execute('SELECT fingerprint,receipt_json FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise ValueError('Model operation ID belongs to another command')
                if prior['receipt_json'] is None:raise ValueError('Incompatible earlier operation unresolved; preserve original')
                return json.loads(prior['receipt_json'])
            if conn.execute('SELECT 1 FROM sessions WHERE session_id=?',(session_id,)).fetchone() is None:raise ValueError('Session not found')
            receipt={'ok':False,'operation_id':operation_id,'domain':'model_choice','session_id':session_id,'http_status':409,
                'error':'Pending model choice cancelled before commit; current model unchanged', 'result':{'cancelled':True}}
            conn.execute("INSERT INTO control_operations VALUES(?,?,'settled',?,?)",(operation_id,fingerprint,json.dumps(receipt),time.time()))
        return receipt

    def save_model_choice(self, session_id: str, choice: dict[str, Any] | None, *, operation_id: str, expected_revision: int, actor: str, requested_model: str | None) -> dict[str, Any]:
        """Existing metadata and control receipt committed together; no model execution."""
        fingerprint=self._model_choice_fingerprint(session_id,operation_id,expected_revision,actor,requested_model)
        if choice is not None and set(choice)!={'model','provider'}:raise ValueError('Only model/provider defaults may change')
        with self._immediate() as conn:
            prior=conn.execute('SELECT fingerprint,receipt_json FROM control_operations WHERE operation_id=?',(operation_id,)).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise ValueError('Model operation ID belongs to another command')
                if prior['receipt_json'] is None:raise ValueError('Earlier model operation unresolved; inspect without replay')
                return json.loads(prior['receipt_json'])
            row=conn.execute('SELECT metadata_json FROM sessions WHERE session_id=?',(session_id,)).fetchone()
            if row is None:raise ValueError('Session not found')
            meta=_row_meta(row['metadata_json'])
            revision=self.model_choice_revision(meta)
            if choice is None:
                receipt={'ok':False,'operation_id':operation_id,'domain':'model_choice','session_id':session_id,'http_status':409,'error':'Model availability could not be validated; current choice retained'}
            elif revision!=expected_revision:
                receipt={'ok':False,'operation_id':operation_id,'domain':'model_choice','session_id':session_id,'http_status':409,'error':'Conversation model changed; read current settings before reviewing a new choice'}
            else:
                meta.update(choice);meta['model_choice_revision']=revision+1
                conn.execute('UPDATE sessions SET metadata_json=?,updated_at=? WHERE session_id=?',(json.dumps(meta),time.time(),session_id))
                receipt={'ok':True,'operation_id':operation_id,'domain':'model_choice','session_id':session_id,'http_status':200,'result':{'model':choice['model'],'provider':choice['provider'],'model_choice_revision':revision+1}}
            conn.execute("INSERT INTO control_operations VALUES(?,?,'settled',?,?)",(operation_id,fingerprint,json.dumps(receipt),time.time()))
        return receipt

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
            "execution": _row_meta(row["execution_json"]) if "execution_json" in row.keys() else {},
            "digest_version": row["digest_version"] if "digest_version" in row.keys() else 1,
            "queue_position": row["queue_position"] if "queue_position" in row.keys() else 0,
        }

    def list_requests(self, *, status: str | None = None) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM client_requests WHERE status=? ORDER BY created_at",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM client_requests ORDER BY created_at"
                ).fetchall()
            return [self._request_row(r) for r in rows]

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

    def latest_request(self, session_id: str) -> dict[str, Any] | None:
        """Return the most recent admitted request for a session."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? "
                "AND status NOT IN ('queued', 'paused') "
                "ORDER BY created_at DESC LIMIT 1", (session_id,),
            ).fetchone()
            return self._request_row(row) if row else None

    def sessions_with_queue(self) -> list[str]:
        """Sessions that still own queued or paused follow-up work."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT session_id FROM client_requests "
                "WHERE status IN ('queued', 'paused') ORDER BY session_id"
            ).fetchall()
            return [r["session_id"] for r in rows]

    def list_queue(self, session_id: str) -> list[dict[str, Any]]:
        """Gateway-owned follow-up queue, ordered by explicit position."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? AND status IN ('queued', 'paused') "
                "ORDER BY queue_position, created_at, request_id",
                (session_id,),
            ).fetchall()
            return [self._request_row(r) for r in rows]

    def enqueue_request(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        requested: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically add a durable follow-up request without starting it.

        A queued item is a real client_request with a frozen execution snapshot.
        It is not transcript-visible until promotion, because the operator may
        edit or remove it before it runs. The session's one-active-turn
        invariant is unchanged.
        """
        if not str(text or "").strip():
            raise ValueError("Missing queue text")
        text = str(text).strip()
        rid = str(request_id or uuid.uuid4().hex)
        if not rid or len(rid) > REQUEST_ID_MAX:
            raise ValueError("Invalid request_id")
        choices = _normalize_requested(requested)
        digest = request_fingerprint(text, choices)
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
                if existing["digest_version"] == 1:
                    same = existing["digest"] == input_fingerprint(text)
                else:
                    same = existing["digest"] == digest
                if not same:
                    raise RequestConflict("Request identity was already used for different input")
                payload = self._request_row(existing)
                payload["replayed"] = True
                payload["accepted"] = False
                return payload
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM client_requests WHERE session_id=? AND status IN ('queued', 'paused')",
                (session_id,),
            ).fetchone()["n"]
            if count >= MAX_QUEUE_PER_SESSION:
                raise RequestBusy("Session queue is full")
            session = conn.execute(
                "SELECT workspace, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            meta = _row_meta(session["metadata_json"] if session else "{}")
            execution = self._resolve_execution(conn, session_id, choices, meta,
                                                session["workspace"] if session else "")
            position = conn.execute(
                "SELECT COALESCE(MAX(queue_position), 0) + 1 AS p FROM client_requests "
                "WHERE session_id=? AND status IN ('queued', 'paused')",
                (session_id,),
            ).fetchone()["p"]
            turn_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO client_requests (
                    request_id, session_id, digest, turn_id, native_run_id, native_session,
                    status, input_text, result_json, owner_pid, created_at, updated_at,
                    execution_json, digest_version, queue_position, requested_json
                ) VALUES (?, ?, ?, ?, NULL, NULL, 'queued', ?, '{}', ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, session_id, digest, turn_id, text, pid, now, now,
                 json.dumps(execution, sort_keys=True), REQUEST_FINGERPRINT_VERSION, int(position),
                 json.dumps(choices, sort_keys=True)),
            )
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (rid,)
            ).fetchone()
            payload = self._request_row(row)
            payload.update({
                "replayed": False,
                "accepted": True,
                "queued": True,
            })
            return payload

    def update_queue_item(
        self,
        session_id: str,
        request_id: str,
        *,
        text: str | None = None,
        status: str | None = None,
        position: int | None = None,
        expected_updated_at: float | None = None,
    ) -> dict[str, Any] | None:
        """Edit only a still-queued item; running work is immutable."""
        if status is not None and status not in QUEUE_STATUSES:
            raise ValueError("Queue status must be queued or paused")
        now = time.time()
        with self._immediate() as conn:
            row = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=? AND session_id=?",
                (request_id, session_id),
            ).fetchone()
            if row is None or row["status"] not in QUEUE_STATUSES:
                return None
            if expected_updated_at is not None and row['updated_at'] != expected_updated_at:
                raise RequestConflict('Queued request changed; refresh before editing')
            if text is not None:
                clean = str(text).strip()
                if not clean:
                    raise ValueError("Queue text cannot be empty")
                requested = _row_meta(row["requested_json"]) if "requested_json" in row.keys() else {}
                digest = request_fingerprint(clean, requested)
                conn.execute(
                    "UPDATE client_requests SET input_text=?, digest=?, updated_at=? WHERE request_id=?",
                    (clean, digest, now, request_id),
                )
            if status is not None:
                conn.execute(
                    "UPDATE client_requests SET status=?, updated_at=? WHERE request_id=?",
                    (status, now, request_id),
                )
            if position is not None:
                clean_pos = max(1, int(position))
                conn.execute(
                    "UPDATE client_requests SET queue_position=?, updated_at=? WHERE request_id=?",
                    (clean_pos, now, request_id),
                )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            return self._request_row(updated) if updated else None

    def reorder_queue(self, session_id: str, ordered_ids: list[str]) -> list[dict[str, Any]]:
        """Assign explicit positions to every queued/paused item in one transaction."""
        ids = [str(v).strip() for v in ordered_ids if str(v).strip()]
        with self._immediate() as conn:
            rows = conn.execute(
                "SELECT request_id FROM client_requests WHERE session_id=? AND status IN ('queued', 'paused')",
                (session_id,),
            ).fetchall()
            existing = {r["request_id"] for r in rows}
            if len(ids) != len(existing) or set(ids) != existing:
                raise ValueError("Queue order must name every queued item exactly once")
            for position, rid in enumerate(ids, 1):
                conn.execute(
                    "UPDATE client_requests SET queue_position=?, updated_at=? WHERE request_id=? AND session_id=?",
                    (position, time.time(), rid, session_id),
                )
        return self.list_queue(session_id)

    def delete_queue_item(self, session_id: str, request_id: str) -> bool:
        with self._immediate() as conn:
            changed = conn.execute(
                "DELETE FROM client_requests WHERE request_id=? AND session_id=? AND status IN ('queued', 'paused')",
                (request_id, session_id),
            )
            return changed.rowcount > 0

    def promote_next_queue_item(self, session_id: str) -> dict[str, Any] | None:
        """Promote one queued request only when the session is idle.

        This is the queue drain point. Paused items are skipped, and a busy
        or unreconciled session cannot start new work.
        """
        now = time.time()
        with self._immediate() as conn:
            session = conn.execute(
                "SELECT status, workspace, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if session is None or session["status"] in {"running", "execution_unknown", "cancelling"}:
                return None
            row = conn.execute(
                "SELECT * FROM client_requests WHERE session_id=? AND status='queued' "
                "ORDER BY queue_position, created_at, request_id LIMIT 1",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            execution = _row_meta(row["execution_json"])
            visible = execution.get("display_text") or row["input_text"]
            msg_id = self.append_message(session_id, "user", visible, timestamp=now, conn=conn,
                                         meta={"request_id": row["request_id"], "turn_id": row["turn_id"]},
                                         parts=_attachment_parts(conn, session_id, execution))
            meta = _row_meta(session["metadata_json"])
            choices = _row_meta(row['requested_json'])
            # A queued implicit default is an execution snapshot, not authority
            # to revert a newer explicit conversation preference on promotion.
            if 'model' in choices:
                meta['model'] = execution.get('model')
                meta['provider'] = execution.get('provider')
            elif 'provider' in choices:
                meta['provider'] = execution.get('provider')
            if 'model' in choices or 'provider' in choices:
                meta['model_choice_revision'] = self.model_choice_revision(meta) + 1
            conn.execute(
                "UPDATE client_requests SET status='admitted', updated_at=? WHERE request_id=?",
                (now, row["request_id"]),
            )
            conn.execute(
                "UPDATE sessions SET status='running', metadata_json=?, updated_at=? WHERE session_id=?",
                (json.dumps(meta), now, session_id),
            )
            event = self._insert_event(
                conn,
                session_id,
                "turn.start",
                {
                    "turn_id": row["turn_id"],
                    "request_id": row["request_id"],
                    "message_id": msg_id,
                    "text": visible,
                },
                now,
            )
            updated = conn.execute(
                "SELECT * FROM client_requests WHERE request_id=?", (row["request_id"],)
            ).fetchone()
            payload = self._request_row(updated)
            payload.update({
                "event": event,
                "message_id": msg_id,
                "accepted": True,
                "replayed": False,
            })
            return payload

    def admit_request(
        self,
        session_id: str,
        text: str,
        *,
        request_id: str | None = None,
        requested: dict[str, Any] | None = None,
        expected_model_revision: int | None = None,
        admission_guard: Callable[[sqlite3.Connection], None] | None = None,
    ) -> dict[str, Any]:
        """Atomically accept a client request and freeze what it executes.

        ``requested`` carries the client's explicit execution choices
        (``EXECUTION_INPUT_KEYS``). They are part of the request identity:
        an identical retry replays the original receipt and changes nothing;
        the same request_id with a different text *or* different choices is
        a :class:`RequestConflict`.

        On acceptance the *resolved* execution input — explicit choices, else
        the session's current defaults, plus the attachment revisions present
        right now — is persisted with the request in the same transaction.
        Execution reads that snapshot, so a later session edit or upload can
        never alter a request that was already admitted. An explicit model
        choice also becomes the session default for later turns (existing
        continuity contract), but only when the request is accepted, never on
        replay.

        Pre-upgrade receipts (``digest_version`` 1, text-only digest) replay
        by their original digest with their original (empty) snapshot; they
        are never recomputed under the new schema or executed again.

        Returns a dict with ``replayed`` True when an existing execution is
        returned. Raises RequestConflict / RequestBusy on illegal reuse and
        ValueError on invalid input (including unknown attachment ids).
        """
        if not str(text or "").strip():
            raise ValueError("Missing turn text")
        text = str(text).strip()
        rid = str(request_id or uuid.uuid4().hex)
        if not rid or len(rid) > REQUEST_ID_MAX:
            raise ValueError("Invalid request_id")
        choices = _normalize_requested(requested)
        digest = request_fingerprint(text, choices)
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
                if existing["digest_version"] == 1:
                    same = existing["digest"] == input_fingerprint(text)
                else:
                    same = existing["digest"] == digest
                if not same:
                    raise RequestConflict(
                        "Request identity was already used for different input"
                    )
                payload = self._request_row(existing)
                payload["replayed"] = True
                payload["accepted"] = False
                return payload
            session = conn.execute(
                "SELECT status, workspace, metadata_json FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            status = session["status"] if session else "idle"
            if status in {"running", "execution_unknown", "cancelling"}:
                raise RequestBusy(
                    "Previous execution needs reconciliation before another turn"
                    if status == "execution_unknown"
                    else "Turn already in progress"
                )
            meta = _row_meta(session["metadata_json"] if session else "{}")
            if expected_model_revision is not None and self.model_choice_revision(meta)!=expected_model_revision:
                raise RequestConflict("Conversation model changed during validation; no new request admitted")
            execution = self._resolve_execution(conn, session_id, choices, meta,
                                                session["workspace"] if session else "")
            if "model" in choices:
                meta["model"] = choices["model"]
                if choices.get("provider"):
                    meta["provider"] = choices["provider"]
                else:
                    # A new model without a provider must not inherit the
                    # previous model's provider (it was paired with that model).
                    meta.pop("provider", None)
            elif choices.get("provider"):
                meta["provider"] = choices["provider"]
            if "model" in choices or "provider" in choices:
                meta["model_choice_revision"] = self.model_choice_revision(meta) + 1
            if admission_guard is not None:
                admission_guard(conn)
            turn_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO client_requests (
                    request_id, session_id, digest, turn_id, native_run_id, native_session,
                    status, input_text, result_json, owner_pid, created_at, updated_at,
                    execution_json, digest_version
                ) VALUES (?, ?, ?, ?, NULL, NULL, 'admitted', ?, '{}', ?, ?, ?, ?, ?)
                """,
                (rid, session_id, digest, turn_id, text, pid, now, now,
                 json.dumps(execution, sort_keys=True), REQUEST_FINGERPRINT_VERSION),
            )
            visible = choices["display_text"] if "display_text" in choices else text
            msg_id = self.append_message(session_id, "user", visible, timestamp=now, conn=conn,
                                         meta={"request_id": rid, "turn_id": turn_id},
                                         parts=_attachment_parts(conn, session_id, execution))
            conn.execute(
                "UPDATE sessions SET status='running', metadata_json=?, updated_at=? WHERE session_id=?",
                (json.dumps(meta), now, session_id),
            )
            event = self._insert_event(
                conn,
                session_id,
                "turn.start",
                {"turn_id": turn_id, "request_id": rid, "message_id": msg_id, "text": visible},
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
                "execution": execution,
                "digest_version": REQUEST_FINGERPRINT_VERSION,
                "message_id": msg_id,
                "event": event,
                "replayed": False,
                "accepted": True,
            }

    @staticmethod
    def _resolve_execution(
        conn: sqlite3.Connection,
        session_id: str,
        choices: dict[str, Any],
        meta: dict[str, Any],
        session_workspace: str,
    ) -> dict[str, Any]:
        """Resolve explicit choices against session defaults, inside the
        admission transaction, into the immutable execution snapshot."""
        if "model" in choices:
            model = choices["model"]
            provider = choices.get("provider")
        else:
            model = meta.get("model")
            provider = choices.get("provider") or meta.get("provider")
        rows = conn.execute(
            "SELECT attachment_id, sha256, size_bytes, provenance FROM attachments "
            "WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        available = {r["attachment_id"]: r for r in rows}
        wanted = choices.get("attachment_ids")
        if wanted is None:
            # Key absent: path-registered attachments ride along as before;
            # staged uploads (POST .../attachments/upload) never do. Key present
            # (even []): exactly the listed ids, of either kind (else branch).
            selected = [r["attachment_id"] for r in rows if r["provenance"] != "upload_staged"]
        else:
            unknown = [a for a in wanted if a not in available]
            if unknown:
                raise ValueError(f"Unknown attachment id(s): {', '.join(unknown)}")
            selected = list(wanted)
        return {
            "model": model or None,
            "provider": provider or None,
            "attachments": [
                {"attachment_id": a, "sha256": available[a]["sha256"],
                 "size_bytes": available[a]["size_bytes"]}
                for a in selected
            ],
            "workspace": choices.get("workspace") or session_workspace or "",
            "options": choices.get("options") or {},
            "allowed_tools": choices.get("allowed_tools"),
            "display_text": choices["display_text"] if "display_text" in choices else None,
            "is_subordinate": bool(choices.get("is_subordinate")),
            "interaction_tier": choices.get("interaction_tier") or meta.get("interaction_tier"),
            "caller": choices.get("caller"),
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
            # execution_unknown is an outcome awaiting reconciliation, not a state to resume
            # from: a worker still unwinding after a stop must not turn it back into 'running'.
            if row["status"] in {"completed", "failed", "cancelled", "execution_unknown"}:
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
                from jaeger_ai.core.gateway.turn_parts import PART_EVENTS, project_parts
                marks = ",".join("?" * len(PART_EVENTS))
                turn_events = [
                    {"event": e["event"], "data": json.loads(e["data_json"] or "{}"), "timestamp": e["timestamp"]}
                    for e in conn.execute(
                        f"SELECT event, data_json, timestamp FROM activity_history WHERE session_id=? AND event IN ({marks}) "
                        "AND json_extract(data_json, '$.request_id')=? ORDER BY event_id ASC",
                        (row["session_id"], *PART_EVENTS, request_id),
                    )
                ]
                turn_parts = project_parts(turn_events)
                for appr in conn.execute(
                    "SELECT approval_id, kind, status, decision, metadata_json FROM approvals "
                    "WHERE request_id=? ORDER BY created_at", (request_id,)):
                    ameta = _row_meta(appr["metadata_json"])
                    turn_parts.append({"type": "approval", "approval_id": appr["approval_id"],
                                       "call_id": ameta.get("call_id"), "tool": ameta.get("tool"),
                                       "target": ameta.get("target"), "status": appr["status"],
                                       "decision": appr["decision"]})
                self.append_message(row["session_id"], "assistant", assistant_text, timestamp=now, conn=conn,
                                    meta={"request_id": request_id, "turn_id": row["turn_id"]},
                                    parts=turn_parts or None)
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
                "AND status NOT IN ('completed', 'failed', 'cancelled') "
                "AND NOT (status='execution_unknown' AND ?='cancelling')",
                (status, now, request_id, status),
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
        if session_id != "*":
            conn.execute("INSERT INTO activity_history VALUES (?, ?, ?, ?, ?)",
                         (event_id, session_id, event, json.dumps(data), now))
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

    def proactive_notifications(self, since_event_id: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        """Durable ``notification.proactive`` events across sessions, oldest first."""
        limit = max(1, min(int(limit or 20), 100))
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT event_id, session_id, data_json, timestamp FROM activity_history "
                "WHERE event='notification.proactive' AND event_id > ? ORDER BY event_id DESC LIMIT ?",
                (int(since_event_id or 0), limit),
            ).fetchall()
        out = []
        for row in reversed(rows):
            try:
                data = json.loads(row["data_json"] or "{}")
            except json.JSONDecodeError:
                data = {}
            out.append({"event_id": int(row["event_id"]), "session_id": row["session_id"],
                        "timestamp": row["timestamp"], **(data if isinstance(data, dict) else {})})
        return out

    def latest_event(self, event: str) -> dict[str, Any] | None:
        """The newest durable event with this name across sessions, or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT event_id, session_id, data_json, timestamp FROM activity_history "
                "WHERE event=? ORDER BY event_id DESC LIMIT 1", (event,),
            ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
        return {"event_id": int(row["event_id"]), "session_id": row["session_id"],
                "timestamp": row["timestamp"], **(data if isinstance(data, dict) else {})}

    def append_event(self, session_id: str, event: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._immediate() as conn:
            return self._insert_event(conn, session_id, event, data)

    def message_feedback(self, session_id: str) -> dict[str, str]:
        """Return the latest durable rating for each message in a session."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT data_json FROM activity_history WHERE session_id=? AND event='message.feedback' ORDER BY event_id",
                (session_id,),
            ).fetchall()
        result: dict[str, str] = {}
        for row in rows:
            data = _row_meta(row["data_json"])
            message_id, rating = data.get("message_id"), data.get("rating")
            if message_id is not None and rating in {"positive", "negative"}:
                result[str(message_id)] = rating
        return result

    def message_reactions(self, session_id: str) -> dict[str, Any]:
        """Durable per-request/per-role decoration, independent of SSE retention."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT event_id,data_json FROM activity_history WHERE session_id=? AND event='message.reaction' ORDER BY event_id", (session_id,)).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            data = _row_meta(row['data_json'])
            key = data['request_id'] + '|' + data['role']
            values = result.setdefault(key, [])
            if data['active'] and data['emoji'] not in values:
                values.append(data['emoji'])
            elif not data['active'] and data['emoji'] in values:
                values.remove(data['emoji'])
        return {'reactions': result, 'event_id': rows[-1]['event_id'] if rows else 0}

    def set_message_reaction(self, session_id: str, request_id: str, role: str, emoji: str, active: bool) -> dict:
        from jaeger_ai.contract.message_feedback import REACTION_EMOJIS
        if not isinstance(role, str) or role not in {'user', 'assistant'} or emoji not in REACTION_EMOJIS or type(active) is not bool:
            raise ValueError('Invalid reaction')
        event = None
        with self._immediate() as conn:
            if conn.execute('SELECT 1 FROM client_requests WHERE session_id=? AND request_id=?', (session_id, request_id)).fetchone() is None:
                raise KeyError('Request not found in this conversation')
            row = conn.execute("SELECT data_json FROM activity_history WHERE session_id=? AND event='message.reaction' AND json_extract(data_json,'$.request_id')=? AND json_extract(data_json,'$.role')=? AND json_extract(data_json,'$.emoji')=? ORDER BY event_id DESC LIMIT 1", (session_id, request_id, role, emoji)).fetchone()
            previous = bool(_row_meta(row['data_json']).get('active')) if row else False
            if previous != active:
                event = self._insert_event(conn, session_id, 'message.reaction', {'request_id': request_id, 'role': role, 'emoji': emoji, 'active': active})
        return {**self.message_reactions(session_id), '_event': event}

    def activity_history(self, session_id: str, after: int = 0, limit: int = 500) -> dict[str, Any]:
        """Paged durable work history; independent of the bounded SSE replay window."""
        limit = max(1, min(limit, 500))
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM activity_history WHERE session_id=? AND event_id>? "
                "ORDER BY event_id LIMIT ?", (session_id, after, limit + 1),
            ).fetchall()
            events = [{**dict(row), "data": json.loads(row["data_json"])} for row in rows[:limit]]
            for event in events:
                del event["data_json"]
            return {"events": events, "has_more": len(rows) > limit,
                    "next_cursor": events[-1]["event_id"] if events else after}

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
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        aid = approval_id or f"approval_{uuid.uuid4().hex[:12]}"
        def insert(conn):
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
            return self._approval_row(conn.execute("SELECT * FROM approvals WHERE approval_id=?", (aid,)).fetchone())
        if connection is not None:
            if not connection.in_transaction:
                raise ValueError("Approval admission requires an owner transaction")
            return insert(connection)
        with self._immediate() as conn:
            return insert(conn)

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

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at"
            ).fetchall()
            return [self._approval_row(r) for r in rows]

    def expire_orphaned_tool_confirms(self) -> int:
        """Close ``tool_confirm`` approvals left by a previous process.

        Their waiter was a thread in that process; it is gone, and the tool
        call it guarded was refused with it. Left ``pending`` they are offered
        on the phone forever and approving one does nothing. Handoff
        approvals resume from stored state and are not touched.
        """
        with self._immediate() as conn:
            cur = conn.execute(
                "UPDATE approvals SET status='resolved', decision='expired', resolved_at=? "
                "WHERE status='pending' AND kind='tool_confirm'",
                (time.time(),),
            )
            return cur.rowcount

    def resolve_approval(
        self,
        approval_id: str,
        *,
        approved: bool,
        decision: str | None = None,
        expected_session_id: str | None = None,
        expected_request_id: str | None = None,
        expected_profile: str | None = None,
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
            if any(value is not None for value in (expected_session_id, expected_request_id, expected_profile)):
                # Native recovered decisions bind to the exact still-live permission context.
                if not all((expected_session_id, expected_request_id, expected_profile)):
                    return None
                if row["session_id"] != expected_session_id or row["request_id"] != expected_request_id:
                    return None
                session = conn.execute("SELECT profile FROM sessions WHERE session_id=?", (expected_session_id,)).fetchone()
                request = conn.execute("SELECT session_id, status FROM client_requests WHERE request_id=?", (expected_request_id,)).fetchone()
                if (not session or session["profile"] != expected_profile or not request
                        or request["session_id"] != expected_session_id
                        or request["status"] not in ("admitted", "running", "awaiting_approval")
                        or choice not in json.loads(row["options_json"] or "[]")):
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
            metadata=dict(record.get('metadata') or {})
            if prior:
                previous=json.loads(prior['metadata_json'] or '{}')
                for key in ('cancel_requested','cancel_operation_id','cancel_requested_at','cancel_origin_request_id','cancelled_before_admission','parent_binding','parent_binding_state','caller_actor','bridge_origin','requested_model','model_choice'):
                    if key in previous:metadata[key]=previous[key]
            conn.execute(
                """
                INSERT INTO handoffs(
                    id, request_id, from_agent_id, to_agent_id, parent_run_id, child_run_id,
                    task, status, require_approval, approval_id, result_json, metadata_json,
                    created_at, updated_at, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    session_id=COALESCE(handoffs.session_id, excluded.session_id),
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
                    json.dumps(metadata),
                    record.get("created_at") or now,
                    now,
                    record.get("session_id"),
                ),
            )
        return self.get_handoff(record["id"]) or record

    def request_handoff_cancellation(self, handoff_id: str, operation_id: str, *, origin_request_id: str | None = None) -> dict[str, Any]:
        """Monotonic intent. Only prove cancellation when no child was admitted."""
        from jaeger_ai.contract.handoffs import child_request_id
        with self._immediate() as conn:
            row=conn.execute('SELECT * FROM handoffs WHERE id=?',(handoff_id,)).fetchone()
            if row is None:raise KeyError(handoff_id)
            if row['status'] in {'completed','failed','cancelled','denied','rejected'}:return self._handoff_row(row)
            meta=json.loads(row['metadata_json'] or '{}')
            if not meta.get('cancel_requested'):
                meta.update(cancel_requested=True,cancel_operation_id=operation_id,cancel_requested_at=time.time(),cancel_origin_request_id=origin_request_id)
            child=conn.execute('SELECT status FROM client_requests WHERE request_id=?',(child_request_id(row['request_id']),)).fetchone()
            status=row['status'];result=json.loads(row['result_json'] or '{}')
            if child is None and status in {'pending_approval','approved','admitted'}:
                status='cancelled';meta['cancelled_before_admission']=True
                result={'ok':False,'status':'cancelled','summary':'Cancelled before child admission; no child execution started','metadata':{'cancellation_confirmed':True,'confirmation_scope':'pre_admission'}}
            conn.execute('UPDATE handoffs SET metadata_json=?,status=?,result_json=?,updated_at=? WHERE id=?',(json.dumps(meta),status,json.dumps(result),time.time(),handoff_id))
            row=conn.execute('SELECT * FROM handoffs WHERE id=?',(handoff_id,)).fetchone()
            return self._handoff_row(row)

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

    #: A handoff's chat session: its own column, else the session of the run
    #: that started it (``parent_run_id`` is a request or turn id).
    _HANDOFF_SESSION_SQL = (
        "COALESCE(h.session_id, (SELECT cr.session_id FROM client_requests cr "
        "WHERE cr.request_id = h.parent_run_id OR cr.turn_id = h.parent_run_id LIMIT 1))"
    )

    # Agent "seen" markers reuse schema_meta (key ``agent_seen:<id>``): one
    # small row per agent, no new table.
    def mark_agent_seen(self, agent_id: str, *, seen_at: float, event_id: int | None = None, unread: bool = False) -> dict[str, Any]:
        record = {"agent_id": agent_id, "seen_at": float(seen_at), "event_id": event_id, "unread": unread}
        with self._immediate() as conn:
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"agent_seen:{agent_id}", json.dumps(record)),
            )
        return record

    def primary_agent_id(self) -> str:
        from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
        with self._immediate() as conn:
            conn.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('agent_primary:operator',?)", (json.dumps(LEAD_AGENT_ID),))
            return self._read_primary_agent(conn)

    @staticmethod
    def _read_primary_agent(conn) -> str:
        from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
        row = conn.execute("SELECT value FROM schema_meta WHERE key='agent_primary:operator'").fetchone()
        value = json.loads(row['value']) if row else LEAD_AGENT_ID
        if not isinstance(value, str) or not value:
            raise ValueError('Invalid operator primary pointer; preserved without overwriting')
        return value

    def set_primary_agent(self, agent_id: str, expected_id: str) -> None:
        if any(not isinstance(v, str) or not v for v in (agent_id, expected_id)):
            raise ValueError('Primary IDs must be nonempty strings')
        from jaeger_ai.core.gateway.agent_presentation import MAX_AGENT_PINS, PresentationConflict
        with self._immediate() as conn:
            if self._read_primary_agent(conn) != expected_id:
                raise PresentationConflict('Primary changed on another client; refresh and retry')
            data = self._read_agent_presentation(conn)
            prefs = data.setdefault(agent_id, {})
            if prefs.get('archived') or prefs.get('deleted'):
                raise PresentationConflict('Restore this agent before making it primary')
            if not prefs.get('pinned'):
                if sum(p.get('pinned') is True for p in data.values()) >= MAX_AGENT_PINS:
                    raise PresentationConflict('Pin slots are full; unpin an agent before replacing primary')
                prefs.update(pinned=True, pin_order=max((p.get('pin_order', -1) for p in data.values()), default=-1) + 1)
            self._write_agent_presentation(conn, data)
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('agent_primary:operator',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(agent_id),))

    # Operator-local presentation metadata shares the existing store/transaction owner.
    def agent_presentation(self) -> dict[str, dict[str, Any]]:
        with self._get_conn() as conn:
            return self._read_agent_presentation(conn)

    @staticmethod
    def _read_agent_presentation(conn) -> dict[str, dict[str, Any]]:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'agent_presentation:operator'").fetchone()
        data = json.loads(row["value"]) if row else {}
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise ValueError("Invalid operator presentation metadata; preserved without overwriting")
        return data

    @staticmethod
    def _write_agent_presentation(conn, data) -> None:
        conn.execute("INSERT INTO schema_meta(key,value) VALUES('agent_presentation:operator',?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(data),))

    @staticmethod
    def _read_agent_sections(conn) -> list[dict[str, Any]]:
        row = conn.execute("SELECT value FROM schema_meta WHERE key='agent_sections:operator'").fetchone()
        data = json.loads(row['value']) if row else []
        if not isinstance(data, list) or any(not isinstance(s, dict) or not isinstance(s.get('id'), str) or not isinstance(s.get('name'), str) for s in data):
            raise ValueError('Invalid section metadata; preserved without overwriting')
        return data

    def agent_sections(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            return self._read_agent_sections(conn)

    def create_agent_section(self, name: str) -> dict[str, Any]:
        from jaeger_ai.core.gateway.agent_presentation import validate_patch
        name = validate_patch({'display_name': name})['display_name']
        if name is None:
            raise ValueError('Section name required')
        with self._immediate() as conn:
            sections = self._read_agent_sections(conn)
            if len(sections) >= 32:
                raise ValueError('At most 32 sections')
            section = {'id': 'section_' + uuid.uuid4().hex, 'name': name, 'order': len(sections)}
            sections.append(section)
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('agent_sections:operator',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(sections),))
            return section

    def patch_agent_presentation(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        from jaeger_ai.core.gateway.agent_presentation import validate_patch, MAX_AGENT_PINS
        patch = validate_patch(body)
        with self._immediate() as conn:
            data = self._read_agent_presentation(conn)
            prefs = dict(data.get(agent_id, {}))
            if patch.get('deleted') is True and self._read_primary_agent(conn) == agent_id:
                raise ValueError('Replace the primary bot before deleting it')
            if patch.get('section_id') is not None and patch['section_id'] not in {s['id'] for s in self._read_agent_sections(conn)}:
                raise ValueError('Section not found')
            if patch.get('pinned') is True and not prefs.get('pinned'):
                if sum(v.get('pinned') is True for v in data.values()) >= MAX_AGENT_PINS:
                    raise ValueError(f'At most {MAX_AGENT_PINS} agents can be pinned; unpin an agent first')
                prefs['pin_order'] = max((v.get('pin_order', -1) for v in data.values()), default=-1) + 1
            for key, value in patch.items():
                if value is None:
                    prefs.pop(key, None)
                else:
                    prefs[key] = value
            if prefs.get('pinned') is False:
                prefs.pop('pin_order', None)
            data[agent_id] = prefs
            self._write_agent_presentation(conn, data)
            return prefs

    def set_agent_pins(self, ids: list[str], expected_ids: list[str]) -> None:
        from jaeger_ai.core.gateway.agent_presentation import MAX_AGENT_PINS, PresentationConflict
        if not isinstance(expected_ids, list) or any(not isinstance(i, str) for i in expected_ids) or len(set(expected_ids)) != len(expected_ids):
            raise ValueError("expected_agent_ids must be a unique list of agent IDs")
        if not isinstance(ids, list) or len(ids) > MAX_AGENT_PINS or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError(f'agent_ids must be a unique list of at most {MAX_AGENT_PINS} agent IDs')
        with self._immediate() as conn:
            data = self._read_agent_presentation(conn)
            current = sorted((key for key, prefs in data.items() if prefs.get('pinned') is True), key=lambda key: data[key].get('pin_order', 0))
            if current != expected_ids:
                raise PresentationConflict('Pins changed on another client; refresh and retry')
            for key, prefs in data.items():
                prefs['pinned'] = key in ids
                prefs.pop('pin_order', None)
            for index, agent_id in enumerate(ids):
                data.setdefault(agent_id, {}).update(pinned=True, pin_order=index)
            self._write_agent_presentation(conn, data)

    def agents_seen(self) -> dict[str, dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT value FROM schema_meta WHERE key LIKE 'agent_seen:%'").fetchall()
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                record = json.loads(row["value"])
            except (TypeError, ValueError):
                continue
            out[str(record.get("agent_id"))] = record
        return out

    def list_handoffs(
        self,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
        since: float | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Newest first. ``agent_id`` matches either end of the handoff."""
        sql = f"SELECT h.*, {self._HANDOFF_SESSION_SQL} AS resolved_session_id FROM handoffs h"
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append("(h.to_agent_id = ? OR h.from_agent_id = ?)")
            params.extend([agent_id, agent_id])
        if session_id:
            clauses.append(f"{self._HANDOFF_SESSION_SQL} = ?")
            params.append(session_id)
        if since is not None:
            clauses.append("h.updated_at > ?")
            params.append(float(since))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY h.created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._get_conn() as conn:
            rows = conn.execute(sql, params).fetchall()
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
        keys = row.keys()
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
            "session_id": (row["resolved_session_id"] if "resolved_session_id" in keys
                           else row["session_id"] if "session_id" in keys else None),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def add_attachment(self, session_id: str, record: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        aid = str(record.get("attachment_id") or f"att_{uuid.uuid4().hex[:16]}")
        row = {
            "attachment_id": aid,
            "session_id": session_id,
            "original_filename": str(record.get("original_filename") or record.get("filename") or ""),
            "stored_filename": str(record.get("stored_filename") or ""),
            "safe_path": str(record.get("safe_path") or record.get("path") or ""),
            "mime_type": str(record.get("mime_type") or record.get("mime") or "application/octet-stream"),
            "size_bytes": int(record.get("size_bytes") or record.get("size") or 0),
            "sha256": str(record.get("sha256") or "") or None,
            "provenance": str(record.get("provenance") or "remote_upload"),
            "created_at": float(record.get("created_at") or now),
            "metadata": record.get("metadata") if isinstance(record.get("metadata"), dict) else {},
        }
        with self._immediate() as conn:
            conn.execute(
                """
                INSERT INTO attachments(
                    attachment_id, session_id, original_filename, stored_filename,
                    safe_path, mime_type, size_bytes, sha256, provenance, created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["attachment_id"],
                    row["session_id"],
                    row["original_filename"],
                    row["stored_filename"],
                    row["safe_path"],
                    row["mime_type"],
                    row["size_bytes"],
                    row["sha256"],
                    row["provenance"],
                    row["created_at"],
                    json.dumps(row["metadata"]),
                ),
            )
        return row

    def search_session_media(self, session_id: str, query: str, *, after: str = '', limit: int = 25) -> tuple[list[dict[str, Any]], str | None]:
        """Existing session raster attachments only; names never imply file access."""
        from jaeger_ai.contract.file_previews import RASTER_MEDIA_TYPES
        with self._get_conn() as conn:
            conn.create_function('media_casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            rows = conn.execute(
                "SELECT * FROM attachments WHERE session_id=? AND mime_type IN (?,?,?,?) "
                "AND instr(media_casefold(original_filename),?)>0 AND attachment_id>? ORDER BY attachment_id LIMIT ?",
                (session_id, *RASTER_MEDIA_TYPES, query.casefold(), after, limit + 1),
            ).fetchall()
            result = [{**dict(row), 'metadata': _row_meta(row['metadata_json'])} for row in rows[:limit]]
            return result, result[-1]['attachment_id'] if len(rows) > limit else None

    def list_attachments(self, session_id: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()
            out = []
            for r in rows:
                out.append({
                    "attachment_id": r["attachment_id"],
                    "session_id": r["session_id"],
                    "original_filename": r["original_filename"],
                    "stored_filename": r["stored_filename"],
                    "safe_path": r["safe_path"],
                    "mime_type": r["mime_type"],
                    "size_bytes": r["size_bytes"],
                    "sha256": r["sha256"],
                    "provenance": r["provenance"],
                    "created_at": r["created_at"],
                    "metadata": _row_meta(r["metadata_json"]),
                })
            return out


    def append_channel_message_once(self, session_id: str, *, channel: str, conversation_id: str, external_id: str, text: str, author_id: str | None = None) -> dict:
        """Provider message identity, durable inbox delivery only; never run a turn."""
        key = json.dumps(['channel_inbox',channel,conversation_id,external_id])
        digest = input_fingerprint(json.dumps({'session_id':session_id,'text':text,**({'author_id':author_id} if author_id is not None else {})},sort_keys=True))
        with self._immediate() as conn:
            old = conn.execute('SELECT digest,receipt_json FROM background_deliveries WHERE delivery_key=?',(key,)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ValueError('Provider message identity conflicts with existing delivery; original preserved')
                return {**json.loads(old['receipt_json']),'replayed':True}
            if not conn.execute('SELECT 1 FROM sessions WHERE session_id=?',(session_id,)).fetchone():
                raise ValueError('Bound conversation unavailable')
            # Attribution is literal data, never an authenticated owner claim.
            content = '['+channel+' incoming · '+conversation_id[:160]+']\n'+text
            mid = self.append_message(session_id,'user',content,kind='channel_message',
                meta={'channel_id':channel,'provider_conversation_id':conversation_id,'external_message_id':external_id,**({'ingress_author_id':author_id} if author_id is not None else {}),'authority':'incoming_data_only'},conn=conn)
            receipt={'message_id':mid,'session_id':session_id,'execution_admitted':False}
            conn.execute('INSERT INTO background_deliveries(delivery_key,digest,receipt_json) VALUES(?,?,?)',(key,digest,json.dumps(receipt)))
            return {**receipt,'replayed':False}

    def append_handoff_post_once(self, session_id: str, role: str, text: str, *, kind: str, sender_agent_id: str | None, links: dict, meta: dict, parts=None) -> int:
        """Transcript delivery only; reuse the durable delivery receipt/transaction owner."""
        if kind not in {'handoff_request', 'handoff_result'} or not links.get('handoff_id'):
            raise ValueError('A handoff post requires its durable exchange ID')
        key = json.dumps(['handoff_post', links['handoff_id'], session_id, kind, meta.get('status')])
        with self._immediate() as conn:
            old = conn.execute('SELECT digest,receipt_json FROM background_deliveries WHERE delivery_key=?', (key,)).fetchone()
            digest = input_fingerprint(json.dumps({'role': role, 'text': text, 'sender': sender_agent_id, 'links': links, 'meta': meta}, sort_keys=True))
            if old:
                if old['digest'] != digest:
                    raise ValueError('Handoff post identity reused with different content')
                return json.loads(old['receipt_json'])['message_id']
            if not conn.execute('SELECT 1 FROM sessions WHERE session_id=?', (session_id,)).fetchone():
                raise ValueError('Original conversation unavailable')
            existing = conn.execute("SELECT id,content FROM messages WHERE session_id=? AND kind=? AND json_extract(links_json,'$.handoff_id')=? AND json_extract(meta_json,'$.status') IS ? ORDER BY id LIMIT 1", (session_id, kind, links['handoff_id'], meta.get('status'))).fetchone()
            if existing and existing['content'] != text:
                raise ValueError('Existing handoff post has different content; preserve it for reconciliation')
            mid = existing['id'] if existing else self.append_message(session_id, role, text, kind=kind, sender_agent_id=sender_agent_id, links=links, meta=meta, parts=parts, conn=conn)
            conn.execute('INSERT INTO background_deliveries(delivery_key,digest,receipt_json) VALUES(?,?,?)', (key, digest, json.dumps({'message_id': mid})))
            return mid

    def deliver_task_result(self, task_id: str, session_id: str, text: str, status: str,
                            sender_agent_id: str | None = None) -> dict:
        """Atomic owner-only delivery to the originating conversation, exactly once."""
        key = json.dumps(['durable_task', task_id])
        with self._immediate() as conn:
            old = conn.execute('SELECT receipt_json FROM background_deliveries WHERE delivery_key=?', (key,)).fetchone()
            if old:
                return {**json.loads(old[0]), 'replayed': True}
            if not conn.execute('SELECT 1 FROM sessions WHERE session_id=?', (session_id,)).fetchone():
                raise ValueError('Originating session no longer exists; task result remains durable')
            now = time.time()
            cursor = conn.execute(
                "INSERT INTO messages(session_id,role,content,timestamp,kind,sender_agent_id,links_json,meta_json) "
                "VALUES(?,'assistant',?,?,'task_result',?,?,?)",
                (session_id, text, now, sender_agent_id, json.dumps({'task_id': task_id, 'origin_session_id': session_id}), json.dumps({'status': status})))
            conn.execute('UPDATE sessions SET updated_at=? WHERE session_id=?', (now, session_id))
            msg_row = conn.execute('SELECT * FROM messages WHERE id=?', (cursor.lastrowid,)).fetchone()
            message = message_dict(msg_row, session_id)
            event = self._insert_event(conn, session_id, 'message.created', {
                'session_id': session_id, 'message_id': cursor.lastrowid, 'role': 'assistant',
                'text': text, 'content': text, 'task_id': task_id, 'status': status,
                'source': 'durable_task', 'initiated_by': 'agent', 'message': message}, now)
            self._queue_event(self._insert_event(conn, '*', 'message.created',
                                                 {'session_id': session_id, 'message': message}, now))
            receipt = {'task_id': task_id, 'event': event, 'message_id': cursor.lastrowid}
            conn.execute('INSERT INTO background_deliveries VALUES(?,?,?)',
                         (key, input_fingerprint(text), json.dumps(receipt)))
            return {**receipt, 'replayed': False}

    def search_agent_messages(self, agent_id: str, query: str, *, before: int | None = None, limit: int = 20) -> dict[str, Any]:
        """Literal text search within the canonical agent's existing conversations.

        Stable message-ID cursor; no index/store copies, admission or read markers.
        Same metadata/legacy specialist binding as list_sessions(agent_id=...).
        """
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
        if not isinstance(query,str) or not 1<=len(query)<=200 or before is not None and (type(before) is not int or not 1<=before<2**63):
            raise ValueError('Invalid message search query/cursor')
        prefix = specialist_session(agent_id, '')
        where = "(json_extract(s.metadata_json, '$.agent_id') = ? OR (json_extract(s.metadata_json, '$.agent_id') IS NULL AND substr(s.session_id, 1, ?) = ?)) AND instr(unicode_casefold(m.content), unicode_casefold(?)) > 0"
        params: list[Any] = [agent_id, len(prefix), prefix, query]
        if before is not None:
            where += ' AND m.id < ?'
            params.append(before)
        with self._get_conn() as conn:
            conn.create_function('unicode_casefold', 1, lambda value: str(value or '').casefold(), deterministic=True)
            rows = conn.execute('SELECT m.id, m.session_id, m.role, m.kind, m.content, m.timestamp, s.title FROM messages m JOIN sessions s ON s.session_id=m.session_id WHERE ' + where + ' ORDER BY m.id DESC LIMIT ?', [*params, limit + 1]).fetchall()
        hits = []
        for row in rows[:limit]:
            content = str(row['content'] or '')
            folded_position = content.casefold().find(query.casefold())
            position, consumed = 0, 0
            for i, char in enumerate(content):
                if consumed + len(char.casefold()) > folded_position:
                    position = i
                    break
                consumed += len(char.casefold())
            start = max(0, position - 100)
            hits.append({'message_id': str(row['id']), 'session_id': row['session_id'], 'role': row['role'], 'kind': row['kind'], 'title': row['title'],
                         'timestamp': row['timestamp'], 'match_offset':position, 'content_revision':hashlib.sha256(content.encode()).hexdigest(), 'snippet': content[start:start + 500], 'content': content[:8000], 'truncated': len(content) > 8000})
        return {'agent_id': agent_id, 'matches': hits, 'next_before': str(rows[limit - 1]['id']) if len(rows) > limit else None, 'matching': 'literal_unicode_casefold'}

    def agent_message_content(self, agent_id: str, message_id: int, *, offset: int = 0, expected_revision: str | None = None) -> dict[str, Any] | None:
        """Bounded read of one exact agent-bound saved message; never selection/read mutation."""
        from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
        if type(message_id) is not int or not 1<=message_id<2**63 or type(offset) is not int or offset<0:
            raise ValueError('Invalid message identity/offset')
        prefix=specialist_session(agent_id,'')
        with self._get_conn() as conn:
            row=conn.execute("SELECT m.* FROM messages m JOIN sessions s ON s.session_id=m.session_id WHERE m.id=? AND (json_extract(s.metadata_json,'$.agent_id')=? OR (json_extract(s.metadata_json,'$.agent_id') IS NULL AND substr(s.session_id,1,?)=?))",(message_id,agent_id,len(prefix),prefix)).fetchone()
        if row is None:return None
        content=str(row['content'] or '')
        revision=hashlib.sha256(content.encode()).hexdigest()
        if expected_revision is not None and expected_revision!=revision:raise ValueError('Saved message revision changed; search again before reading it')
        if offset>len(content):raise ValueError('Message offset exceeds retained text')
        end=min(len(content),offset+8000)
        return {'agent_id':agent_id,'message_id':str(message_id),'session_id':row['session_id'],
                'role':row['role'],'kind':row['kind'],'content':content[offset:end],
                'offset':offset,'end_offset':end,'total_chars':len(content),'revision':revision,
                'next_offset':end if end<len(content) else None,'previous_offset':max(0,offset-8000) if offset else None}

    def diagnostics_snapshot(self) -> dict[str, Any]:
        """Read-only durable counts/unknown identities; no text, paths or retry."""
        with self._get_conn() as conn:
            conn.execute('BEGIN')
            counts = {}
            for name, table in (('requests', 'client_requests'), ('approvals', 'approvals'), ('handoffs', 'handoffs')):
                counts[name] = {row['status']: row['n'] for row in conn.execute(f'SELECT status, COUNT(*) AS n FROM {table} GROUP BY status')}
            unknown = [dict(row) for row in conn.execute("SELECT request_id, session_id, status FROM client_requests WHERE status='execution_unknown' ORDER BY created_at DESC LIMIT 20")]
            return {'sessions': conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], **counts,
                    'unknown_requests': unknown, 'unknown_list_limit': 20}

    def control_operation(self, operation_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM control_operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        return {"operation_id": operation_id, "status": row["status"],
                "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None}

    def reserve_control_operation(self, operation_id: str, payload: dict[str, Any]) -> bool:
        fingerprint = input_fingerprint(json.dumps(payload, sort_keys=True))
        with self._immediate() as conn:
            old = conn.execute("SELECT fingerprint FROM control_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("Operation identity already belongs to a different action")
                return False
            conn.execute("INSERT INTO control_operations VALUES(?,?,'execution_unknown',NULL,?)",
                         (operation_id, fingerprint, time.time()))
            return True

    def reserve_scoped_control_operation(self, operation_id: str, payload: dict[str, Any], scope: str) -> bool:
        """A lost lifecycle receipt blocks fresh commands for the same resource.

        Existing control_operations owns receipts; schema_meta holds only the
        resource's latest command pointer, surviving process/client restarts.
        """
        fingerprint = input_fingerprint(json.dumps(payload, sort_keys=True))
        with self._immediate() as conn:
            old = conn.execute('SELECT fingerprint FROM control_operations WHERE operation_id=?', (operation_id,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise ValueError('Operation identity already belongs to a different action')
                return False
            key = 'control_scope:' + scope
            previous = conn.execute('SELECT value FROM schema_meta WHERE key=?', (key,)).fetchone()
            if previous:
                prior = conn.execute('SELECT receipt_json FROM control_operations WHERE operation_id=?', (previous['value'],)).fetchone()
                if prior is None or prior['receipt_json'] is None:
                    raise ValueError('Earlier resource operation is unresolved: ' + previous['value'] + '; inspect without retry')
            conn.execute("INSERT INTO control_operations VALUES(?,?,'execution_unknown',NULL,?)", (operation_id, fingerprint, time.time()))
            conn.execute('INSERT INTO schema_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key,operation_id))
        return True

    def finish_control_operation(self, operation_id: str, receipt: dict[str, Any]) -> None:
        with self._immediate() as conn:
            conn.execute("UPDATE control_operations SET status='settled', receipt_json=? WHERE operation_id=?",
                         (json.dumps(receipt), operation_id))
