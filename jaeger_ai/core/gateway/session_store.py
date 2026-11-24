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
import logging
import threading
from typing import Any, Callable, Iterator

from jaeger_ai.contract import trace as _trace
from jaeger_ai.core.gateway import agent_activity as _agent_activity
from jaeger_ai.core.gateway import handoff_outputs as _handoff_outputs
from jaeger_ai.core.sqlite_connection import ClosingConnection


SCHEMA_VERSION = 16

MAX_RETAINED_EVENTS = 5000
REQUEST_ID_MAX = 128
MAX_QUEUE_PER_SESSION = 100
QUEUE_STATUSES = frozenset({'queued', 'paused'})


class RequestConflict(ValueError):
    """A client request_id was reused with a different input fingerprint."""


class RequestBusy(RuntimeError):
    """A session already has in-flight or unreconciliation work."""


class StateConflict(RuntimeError):
    """A revisioned Gateway state record changed before this write."""


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
            from jaeger_ai.contract.modes import normalize_interaction_tier
            tier_val = str(value).strip().lower()
            if tier_val:
                out[key] = normalize_interaction_tier(tier_val)
        else:
            text = str(value).strip()
            if text:
                out[key] = text
    return out


from jaeger_os.core.process import pid_alive as pid_is_alive  # single owner


def _row_meta(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _message_read_state(meta: dict[str, Any]) -> dict[str, Any]:
    """Do not let imported/older caller metadata break the session read model."""
    value = meta.get('message_read_state')
    if isinstance(value, dict) and type(value.get('event_id')) is int and value['event_id'] >= 0:
        marker = value.get('unread')
        if marker is None or (isinstance(marker, dict) and isinstance(marker.get('request_id'), str)
                              and marker['request_id'] and marker.get('role') in ('user', 'assistant')):
            return {'unread': marker, 'event_id': value['event_id']}
    return {'unread': None, 'event_id': 0}


MESSAGE_KINDS = frozenset({"message", "channel_message", "summary", "handoff_request", "handoff_result", "task_result",
                           "room_message", "room_reply"})
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


GENERIC_SESSION_TITLES = {
    "",
    "new conversation",
    "new chat",
    "jaeger stable chat",
    "chat with jaeger",
    "untitled conversation",
    "untitled",
}


def is_generic_session_title(title: str | None, metadata: dict[str, Any] | None = None) -> bool:
    meta = metadata or {}
    if isinstance(meta.get("chat_organization"), dict) and meta["chat_organization"].get("manual_title"):
        return False
    return (title or "").strip().lower() in GENERIC_SESSION_TITLES


def title_from_user_text(content: str) -> str:
    line = " ".join((content or "").split())
    if not line:
        return ""
    if len(line) > 60:
        trimmed = line[:60].rsplit(" ", 1)[0].rstrip(".,;:")
        line = (trimmed or line[:60]).rstrip() + "…"
    return line[:200]


_HIDDEN_SQL = "(json_extract(meta_json, '$.hidden') IS NULL OR json_extract(meta_json, '$.hidden') = 0)"


def _message_hidden(meta_json: Any) -> bool:
    return bool(_row_meta(meta_json).get("hidden"))


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
    if isinstance(extra.get("versions"), list) and extra["versions"]:
        out["versions"] = extra["versions"]
        idx = extra.get("version_index")
        out["version_index"] = idx if isinstance(idx, int) else len(extra["versions"]) - 1
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
    if isinstance(extra.get("versions"), list) and extra["versions"]:
        out["versions"] = extra["versions"]
        idx = extra.get("version_index")
        out["version_index"] = idx if isinstance(idx, int) else len(extra["versions"]) - 1
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


from .store import AgentStoreMixin, RequestStoreMixin, SessionDomainStoreMixin


class GatewaySessionStore(AgentStoreMixin, RequestStoreMixin, SessionDomainStoreMixin):
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_store_path()
        #: Called with each event record the store writes itself (message.created),
        #: after its transaction commits. The event bus attaches its fanout here.
        self.event_listener: Callable[[dict[str, Any]], Any] | None = None
        self._pending_events = threading.local()
        self._init_db()
        try:
            self.backfill_generic_titles()
        except Exception:
            pass


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
        conn = sqlite3.connect(str(self.path), timeout=10.0, factory=ClosingConnection)
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
            # Additive, idempotent: existing stores (any schema version) gain it too.
            conn.executescript("""
                -- Server-produced clarify forms (GB-033): one revisioned entity per
                -- question, resolved exactly once (answered | cancelled | expired).
                CREATE TABLE IF NOT EXISTS clarify_forms (
                    clarify_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    request_id TEXT,
                    question TEXT NOT NULL,
                    choices_json TEXT NOT NULL DEFAULT '[]',
                    revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    answer TEXT,
                    created_at REAL NOT NULL,
                    resolved_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_clarify_session ON clarify_forms(session_id, status);
            """)

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
        if current < 16:
            # Shared operator projection.  Browser, Mac, iPhone and IDE clients
            # read the same active conversation after reconnect or restart;
            # no UI window owns a competing current-session preference.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS operator_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    updated_by TEXT NOT NULL
                )
            """)
            current = 16
        self._ensure_title_source(conn)
        self._ensure_session_topics(conn)
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








    def update_status(self, session_id: str, status: str) -> None:
        now = time.time()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                (status, now, session_id),
            )





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

















    def _emit(self, events: list[dict[str, Any]]) -> None:
        sink = getattr(self, "event_sink", None)
        for event in events:
            if sink is not None:
                try:
                    sink(event)
                except Exception:  # noqa: BLE001 — durable row exists; live fanout is best effort
                    pass




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
        options = dict(choices.get("options") or {})
        prior_local = conn.execute("SELECT 1 FROM client_requests WHERE session_id=? "
            "AND json_extract(execution_json, '$.options.local_only')=1 LIMIT 1", (session_id,)).fetchone()
        if options.get("local_only") or meta.get("local_only") or prior_local:
            options["local_only"] = True
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
            "options": options,
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





    def _insert_event(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        event: str,
        data: dict[str, Any],
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        now = timestamp or time.time()
        # The one canonical envelope (contract/trace.py), stamped on the single
        # durable write path so live and replayed frames are identical.
        # Stored inside data_json["trace"]; surfaced as a top-level ``trace``
        # field on read so payload ``data`` stays exactly what the producer sent.
        annotated = _trace.annotate(session_id, event, data, now)
        trace_block = annotated.get("trace") if annotated is not data else None
        cursor = conn.execute(
            "INSERT INTO events(session_id, event, data_json, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, event, json.dumps(annotated), now),
        )
        event_id = int(cursor.lastrowid or 0)
        if session_id != "*":
            conn.execute("INSERT INTO activity_history VALUES (?, ?, ?, ?, ?)",
                         (event_id, session_id, event, json.dumps(data), now))
        if event in _agent_activity.ALL_KINDS:
            try:  # G1: the Agents tab's durable activity row (never blocks the event)
                _agent_activity.ensure(conn)
                _agent_activity.record(conn, event_id, session_id, event, data, now)
            except Exception:  # noqa: BLE001
                __import__("logging").getLogger(__name__).warning("agent activity record failed for %s", event, exc_info=True)
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
            **({"trace": trace_block} if trace_block else {}),
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

    def trace_history(self, session_id: str, before: int | None = None, limit: int = 2000) -> dict[str, Any]:
        """The session's own durable events, newest page first, each with a
        rebuilt ``trace`` — so turns older than the bounded SSE window still
        replay in the Process view. Rows are returned oldest-first."""
        limit = max(1, min(int(limit), 5000))
        cursor = int(before) if before else None
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT event_id, session_id, event, data_json, timestamp FROM activity_history "
                "WHERE session_id=? AND (? IS NULL OR event_id<?) ORDER BY event_id DESC LIMIT ?",
                (session_id, cursor, cursor, limit + 1),
            ).fetchall()
        more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
        starts: dict[str, float] = {}
        events = []
        for row in rows:
            try:
                data = json.loads(row["data_json"])
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict):
                data.pop("trace", None)
            record = {"event_id": row["event_id"], "session_id": row["session_id"], "event": row["event"],
                      "timestamp": row["timestamp"], "data": data}
            trace = _trace.history_trace(row["event"], data, float(row["timestamp"] or 0), starts) \
                if isinstance(data, dict) else None
            if trace:
                record["trace"] = trace
            events.append(record)
        return {"events": events, "has_more": more,
                "oldest_event_id": events[0]["event_id"] if events else None,
                "newest_event_id": events[-1]["event_id"] if events else None}


    def replay_events(
        self,
        session_id: str,
        since_event_id: int = 0,
        *,
        limit: int = 500,
        session_only: bool = False,
    ) -> dict[str, Any]:
        # session_only: this session's rows plus global ("*") rows that name
        # this session (approval.resolved, message.created twins) — not every
        # global board/backlog broadcast.
        scope_sql = ("(session_id = ? OR (session_id = '*' AND json_extract(data_json, '$.session_id') = ?))"
                     if session_only else "session_id IN (?, '*')")
        scope_args: tuple[Any, ...] = (session_id, session_id) if session_only else (session_id,)
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
                f"SELECT * FROM events WHERE {scope_sql} AND event_id > ? "
                "ORDER BY event_id ASC LIMIT ?",
                (*scope_args, since_event_id, max(1, min(limit, MAX_RETAINED_EVENTS))),
            ).fetchall()
            events = [_trace.split_record({
                    "event_id": r["event_id"],
                    "session_id": r["session_id"],
                    "event": r["event"],
                    "data": json.loads(r["data_json"] or "{}"),
                    "timestamp": r["timestamp"],
                }) for r in rows]
            return {
                "events": events,
                "cursor_expired": cursor_expired,
                "oldest_event_id": lo,
                "latest_event_id": hi,
                "valid_cursor": not cursor_expired,
            }





    # ── clarify forms (GB-033) ─────────────────────────────────────────






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







    #: A handoff's chat session: its own column, else the session of the run
    #: that started it (``parent_run_id`` is a request or turn id).
    _HANDOFF_SESSION_SQL = (
        "COALESCE(h.session_id, (SELECT cr.session_id FROM client_requests cr "
        "WHERE cr.request_id = h.parent_run_id OR cr.turn_id = h.parent_run_id LIMIT 1))"
    )

    # Agent "seen" markers reuse schema_meta (key ``agent_seen:<id>``): one
    # small row per agent, no new table.




    # Operator-local presentation metadata shares the existing store/transaction owner.














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
