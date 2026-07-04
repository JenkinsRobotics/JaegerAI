"""The instance's unified data store — ``<instance>/memory/state.db``.

Before Group 9 (0.2.0), the agent's runtime state lived across four
flat files: ``facts.json``, ``episodic.jsonl``,
``episodic.embeddings.npz``, ``schedules.jsonl``. That layout was
clean for alpha-scale instances (a few hundred facts, a few thousand
episodic turns) and human-readable for debugging. But the agent's
trajectory — training-data extraction, multi-instance scale,
concurrent reader+writer — pushes past what flat files do well:

  * Append latency. ``facts.json`` rewrites the whole file on every
    ``remember`` call. At 10K facts that's milliseconds per write;
    at 100K it's painful.
  * Crash safety. Two writes during a power cut can corrupt the
    file. We mitigated with a ``.lock`` + atomic rename; SQLite WAL
    is essentially immune for free.
  * Concurrent access. The flat-file layout serialised every read
    behind ``fcntl.flock``. WAL lets many readers coexist with one
    writer.
  * Queries. "Every turn last week where the agent used
    ``run_python`` AND the user followed up with positive feedback"
    is a 5-line SQL join. Across flat files it's a Python scan.

This module is the foundation everything else in Group 9 builds on:
schema bookkeeping, WAL setup, connection management,
``sqlite-vec`` extension loading (with a graceful Python-cosine
fallback when the extension isn't packaged for the host). The
``facts`` / ``episodic`` / ``schedules`` tables are defined here but
their CRUD wrappers live alongside the existing facade functions in
``core/memory/memory.py`` so the public API
(``remember`` / ``recall`` / ``forget`` / ...) doesn't move.

The DB lives at ``<instance>/memory/state.db``. WAL files
(``state.db-wal``, ``state.db-shm``) sit alongside; backup / restore
handle them transparently because they're in the ``memory/``
subdir.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator


# Bumped on schema changes. Migration writers in
# ``core/memory/migrations/`` apply each step from the on-disk version
# up to ``SCHEMA_VERSION``; the store refuses to open a DB written by
# a newer SCHEMA_VERSION than the current code knows about.
SCHEMA_VERSION = 2

_DB_FILENAME = "state.db"


# ── connection lifecycle ───────────────────────────────────────────


# Per-process singleton connection. The agent loop is single-threaded
# (one model call at a time, gated by the LLM lock), and SQLite in
# WAL mode tolerates many threads sharing one connection if we
# serialize writes ourselves. We pass ``check_same_thread=False``
# and guard writes with ``_write_lock``.
_state: dict[str, Any] = {
    "path": None,           # absolute path to state.db
    "conn": None,           # sqlite3.Connection
    "vec_loaded": False,    # did sqlite-vec successfully load?
}
_write_lock = threading.Lock()


def bind(layout: Any) -> None:
    """Open / reopen the store against an instance layout.

    Called by ``core/memory/memory.py:bind`` so the public memory
    facade and the SQLite store share one connection. Idempotent:
    a re-bind to the same layout no-ops; a re-bind to a different
    layout closes the old connection first.
    """
    db_path = layout.memory_dir / _DB_FILENAME
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if _state["path"] == str(db_path) and _state["conn"] is not None:
        return  # same instance, already open

    close()

    conn = _open(db_path)
    _state["path"] = str(db_path)
    _state["conn"] = conn
    _state["vec_loaded"] = _try_load_vec(conn)
    _ensure_schema(conn)


def close() -> None:
    """Close the active connection if any. Used at shutdown and
    when ``bind`` swaps instances."""
    conn = _state.get("conn")
    if conn is not None:
        with contextlib.suppress(sqlite3.Error):
            conn.close()
    _state["conn"] = None
    _state["path"] = None
    _state["vec_loaded"] = False


def _open(path: Path) -> sqlite3.Connection:
    """Open the DB with the production pragmas: WAL journal, NORMAL
    sync, foreign keys ON, busy-timeout 5s.

    WAL mode is the default. If the underlying filesystem doesn't
    support WAL (NFS, SMB, some sandboxed sandbox FS), SQLite reports
    ``rollback`` from the journal_mode pragma and we fall back to
    DELETE silently.
    """
    conn = sqlite3.connect(
        str(path),
        timeout=5.0,
        isolation_level=None,           # autocommit; we use BEGIN/COMMIT explicitly
        check_same_thread=False,        # see _write_lock
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _try_load_vec(conn: sqlite3.Connection) -> bool:
    """Try to load the ``sqlite-vec`` extension for vector search.

    Returns True on success. False (without raising) when the
    extension isn't installed, can't be loaded on this platform, or
    the SQLite build was compiled without extension loading. The
    agent's ``search_memory`` falls back to Python-side cosine over
    the embedding BLOBs in that case — slower but correct.
    """
    try:
        import sqlite_vec
    except ImportError:
        return False
    try:
        conn.enable_load_extension(True)
    except (AttributeError, sqlite3.NotSupportedError):
        # Some Python builds (Homebrew Python on some macOS versions,
        # older pip-installed SQLite) disable extension loading.
        return False
    try:
        sqlite_vec.load(conn)
    except Exception:  # noqa: BLE001 — package-version-specific failure modes
        return False
    finally:
        with contextlib.suppress(sqlite3.NotSupportedError, AttributeError):
            conn.enable_load_extension(False)
    return True


def has_vec_extension() -> bool:
    """True when ``sqlite-vec`` loaded successfully for this
    process. Exposed for ``search_memory`` and ``--doctor``."""
    return bool(_state.get("vec_loaded"))


# ── schema management ──────────────────────────────────────────────


_SCHEMA_STATEMENTS: tuple[str, ...] = (
    # Schema-version bookkeeping. One row, primary-key 1, so an
    # ``UPDATE`` always hits.
    """CREATE TABLE IF NOT EXISTS schema_version (
        id        INTEGER PRIMARY KEY CHECK (id = 1),
        version   INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",

    # facts — replaces ``facts.json``. ``category`` is the new
    # field added when WIZ-2 / categorised memory landed; default
    # 'general' matches the JSON store's behaviour.
    # facts = the CURRENT view (latest value per subject+key+source).
    #   subject = who/what the fact is ABOUT (the operator by default, or
    #             another person/thing — "many people's colours").
    #   source  = who SET it (user / agent / benchmark) — provenance.
    #   tags/note/category = the 5W1H context + grouping.
    # PK (subject, key, source) so facts about different subjects, or from
    # different sources, coexist instead of clobbering each other.
    """CREATE TABLE IF NOT EXISTS facts (
        subject    TEXT NOT NULL DEFAULT 'user',
        key        TEXT NOT NULL,
        value      TEXT NOT NULL,
        category   TEXT NOT NULL DEFAULT 'general',
        source     TEXT NOT NULL DEFAULT 'user',
        tags       TEXT NOT NULL DEFAULT '',
        note       TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (subject, key, source)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_facts_category ON facts (category)",
    "CREATE INDEX IF NOT EXISTS idx_facts_source ON facts (source)",
    "CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts (subject, key)",

    # fact_log = append-only history of every assertion, so a fact can be
    # traced over time ("Jonathan's favorite colour was blue on d1, black on
    # d2") — the current `facts` row is just the latest. One row per write.
    """CREATE TABLE IF NOT EXISTS fact_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        subject    TEXT NOT NULL DEFAULT 'user',
        key        TEXT NOT NULL,
        value      TEXT NOT NULL,
        category   TEXT NOT NULL DEFAULT 'general',
        source     TEXT NOT NULL DEFAULT 'user',
        tags       TEXT NOT NULL DEFAULT '',
        note       TEXT NOT NULL DEFAULT '',
        ts         TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_fact_log_key ON fact_log (subject, key, ts)",

    # episodic — one row per agent turn. ``session_key`` lets the
    # TUI / messaging gateway / voice loop keep separate histories.
    """CREATE TABLE IF NOT EXISTS episodic (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        session_key     TEXT NOT NULL,
        ts              TEXT NOT NULL,
        user            TEXT,
        answer          TEXT,
        decision_raw    TEXT,
        tool_activity   TEXT,
        latency_ms      INTEGER,
        first_decision  TEXT,
        skipped_final   INTEGER NOT NULL DEFAULT 0,
        meta_json       TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic (session_key, id)",
    "CREATE INDEX IF NOT EXISTS idx_episodic_ts ON episodic (ts)",

    # episodic_embeddings — one row per episodic row, vector as BLOB.
    # Dimension stored in the row so different embedding models can
    # coexist during a transition window.
    """CREATE TABLE IF NOT EXISTS episodic_embeddings (
        episodic_id INTEGER PRIMARY KEY
                    REFERENCES episodic(id) ON DELETE CASCADE,
        model       TEXT NOT NULL,
        dim         INTEGER NOT NULL,
        vector      BLOB NOT NULL
    )""",

    # schedules — replaces ``schedules.jsonl``. ``status`` lets us
    # cancel without rewriting; ``next_fire_at`` is recomputed each
    # time the cron worker dispatches.
    """CREATE TABLE IF NOT EXISTS schedules (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id     TEXT UNIQUE NOT NULL,
        cron            TEXT NOT NULL,
        prompt          TEXT NOT NULL,
        next_fire_at    TEXT,
        status          TEXT NOT NULL DEFAULT 'active',
        session_key     TEXT,
        created_at      TEXT NOT NULL,
        last_fired_at   TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_schedules_status ON schedules (status, next_fire_at)",

    # sessions — DB-3+ work; one row per logical conversation.
    # Optional join target for episodic + tool_calls.
    """CREATE TABLE IF NOT EXISTS sessions (
        session_key  TEXT PRIMARY KEY,
        started_at   TEXT NOT NULL,
        ended_at     TEXT,
        turn_count   INTEGER NOT NULL DEFAULT 0
    )""",

    # tool_calls — DB-6. Every dispatched tool, with full args +
    # result for training-data extraction. ``args_json`` /
    # ``result_json`` redacted via the existing ``redact_obj``.
    """CREATE TABLE IF NOT EXISTS tool_calls (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        episodic_id   INTEGER REFERENCES episodic(id) ON DELETE SET NULL,
        session_key   TEXT NOT NULL,
        tool_name     TEXT NOT NULL,
        args_json     TEXT,
        result_json   TEXT,
        ok            INTEGER NOT NULL DEFAULT 1,
        error         TEXT,
        elapsed_s     REAL,
        ts            TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls (session_key, id)",
    "CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls (tool_name, ts)",

    # audit_log — DB-7. Tamper-evidence trail for sandbox-relevant
    # operations: ``file_write``, ``run_shell``, ``hardline_block``,
    # ``ssh_exec``, etc. Mirror-written alongside the on-disk
    # ``logs/audit.log`` JSONL (which stays the canonical forensic
    # record); SQL gives the daemon's ``--doctor`` + the future
    # ``jaeger memory export`` a queryable shape.
    """CREATE TABLE IF NOT EXISTS audit_log (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        ts            TEXT NOT NULL,
        event         TEXT NOT NULL,
        payload_json  TEXT NOT NULL,
        session_key   TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log (event, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log (ts)",
)


def _migrate_facts_table(conn: sqlite3.Connection) -> None:
    """Rebuild an older ``facts`` table into the v2 shape (subject / source /
    tags / note + composite PK ``(subject, key, source)``). Idempotent: a
    no-op on a fresh DB (no table yet) or one already at v2. Existing rows
    become subject='user', source='user'. Runs before the schema CREATE
    INDEXes that reference the new columns."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'"
    ).fetchone()
    if not exists:
        return
    info = conn.execute("PRAGMA table_info(facts)").fetchall()
    cols = {r[1] for r in info}
    pk = {r[1] for r in info if r[5]}
    if {"subject", "source", "tags", "note"} <= cols and \
            pk == {"subject", "key", "source"}:
        return  # already v2
    subj = "subject" if "subject" in cols else "'user'"
    src = "source" if "source" in cols else "'user'"
    tg = "tags" if "tags" in cols else "''"
    nt = "note" if "note" in cols else "''"
    try:
        conn.executescript(
            f"""
            BEGIN;
            DROP TABLE IF EXISTS _facts_v2;
            CREATE TABLE _facts_v2 (
                subject    TEXT NOT NULL DEFAULT 'user',
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'general',
                source     TEXT NOT NULL DEFAULT 'user',
                tags       TEXT NOT NULL DEFAULT '',
                note       TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (subject, key, source)
            );
            INSERT OR IGNORE INTO _facts_v2
                (subject, key, value, category, source, tags, note, created_at, updated_at)
                SELECT {subj}, key, value, category, {src}, {tg}, {nt},
                       created_at, updated_at
                FROM facts;
            -- Seed the history log so migrated facts are traceable from day
            -- one (recall_history must not return empty for a fact that
            -- demonstrably existed). fact_log may not exist yet — this
            -- migration runs BEFORE the schema statements.
            CREATE TABLE IF NOT EXISTS fact_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                subject    TEXT NOT NULL DEFAULT 'user',
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                category   TEXT NOT NULL DEFAULT 'general',
                source     TEXT NOT NULL DEFAULT 'user',
                tags       TEXT NOT NULL DEFAULT '',
                note       TEXT NOT NULL DEFAULT '',
                ts         TEXT NOT NULL
            );
            INSERT INTO fact_log
                (subject, key, value, category, source, tags, note, ts)
                SELECT subject, key, value, category, source, tags,
                       'migrated from schema v1', updated_at
                FROM _facts_v2;
            DROP TABLE facts;
            ALTER TABLE _facts_v2 RENAME TO facts;
            COMMIT;
            """
        )
    except sqlite3.Error:
        # A mid-script failure leaves the transaction open on this
        # autocommit connection — roll it back explicitly so the old
        # table survives intact, then re-raise (refusing to run on a
        # half-migrated DB beats limping on one).
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        raise


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create / migrate the schema to ``SCHEMA_VERSION``.

    First-open: every CREATE TABLE runs cleanly (IF NOT EXISTS), the
    schema_version row is INSERTed at the target version (v2).

    Same-version reopen: every CREATE TABLE no-ops; the
    schema_version row matches and we just return.

    Older DB (v1 facts shape): ``_migrate_facts_table`` detects the old
    SHAPE (columns + PK, not the version number — robust to partially
    migrated intermediates) and rebuilds ``facts`` into the v2
    subject/source/tags/note form BEFORE the schema statements run,
    because the v2 indexes reference columns a v1 table lacks. The
    version row is then bumped to v2 below.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    cur = conn.cursor()
    # v1 → v2: rebuild an older `facts` table into the subject/source/tags/note
    # shape BEFORE the schema statements — the new indexes reference columns an
    # old table lacks. No-op on a fresh DB or one already at v2.
    _migrate_facts_table(conn)
    cur.executescript("BEGIN; " + "; ".join(_SCHEMA_STATEMENTS) + "; COMMIT;")

    row = conn.execute(
        "SELECT version FROM schema_version WHERE id = 1"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (id, version, created_at, updated_at) "
            "VALUES (1, ?, ?, ?)",
            (SCHEMA_VERSION, now, now),
        )
        return

    current = int(row["version"])
    if current == SCHEMA_VERSION:
        return
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"state.db schema is v{current} but installed core knows "
            f"only v{SCHEMA_VERSION} — upgrade the framework."
        )
    # Older version → future migration runner. Today there's only v1
    # so this branch only fires on an explicit downgrade-of-downgrade
    # test scenario.
    conn.execute(
        "UPDATE schema_version SET version = ?, updated_at = ? WHERE id = 1",
        (SCHEMA_VERSION, now),
    )


# ── connection access ─────────────────────────────────────────────


def connection() -> sqlite3.Connection:
    """Get the live connection. Raises if ``bind`` hasn't been called."""
    conn = _state.get("conn")
    if conn is None:
        raise RuntimeError("sqlite_store not bound — call bind(layout) first")
    return conn


@contextlib.contextmanager
def writer() -> Iterator[sqlite3.Connection]:
    """Acquire the write lock + a transaction. Used by every
    INSERT / UPDATE / DELETE site. Read-only callers use
    ``connection()`` directly.

    The lock + BEGIN IMMEDIATE pair ensures:
      - At most one writer at a time per process.
      - No reader-starvation (WAL lets readers continue throughout).
      - Atomic commit on success; ROLLBACK on any exception.
    """
    conn = connection()
    with _write_lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
        except Exception:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def is_bound() -> bool:
    """True when ``bind`` has been called and the connection is open."""
    return _state.get("conn") is not None


def db_path() -> Path | None:
    """The path of the active state.db, or None when not bound."""
    p = _state.get("path")
    return Path(p) if p else None


__all__ = [
    "SCHEMA_VERSION",
    "bind",
    "close",
    "connection",
    "writer",
    "has_vec_extension",
    "is_bound",
    "db_path",
]
