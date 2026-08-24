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
from collections.abc import Callable, Iterator
from typing import Any


# Bumped on schema changes. Migration writers in
# ``core/memory/migrations/`` apply each step from the on-disk version
# up to ``SCHEMA_VERSION``; the store refuses to open a DB written by
# a newer SCHEMA_VERSION than the current code knows about.
SCHEMA_VERSION = 5

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

    # commitments — durable SI intentions (goals/runs) that survive restart.
    """CREATE TABLE IF NOT EXISTS commitments (
        id            TEXT PRIMARY KEY,
        title         TEXT NOT NULL,
        state         TEXT NOT NULL,
        kind          TEXT NOT NULL DEFAULT 'goal',
        payload_json  TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        parent_id     TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_commitments_state ON commitments (state, updated_at)",

    # runs — one attempt at a commitment. Owns the pid claim and the
    # wake key; see jaeger_agent/cognition/runs.py for the state machine.
    """CREATE TABLE IF NOT EXISTS runs (
        id            TEXT PRIMARY KEY,
        commitment_id TEXT NOT NULL,
        state         TEXT NOT NULL,
        attempt       INTEGER NOT NULL DEFAULT 1,
        owner_pid     INTEGER,
        heartbeat_at  TEXT,
        wake_key      TEXT,
        provider      TEXT,
        reason        TEXT,
        payload_json  TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_runs_state ON runs (state, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_runs_commitment ON runs (commitment_id, attempt)",
    "CREATE INDEX IF NOT EXISTS idx_runs_wake ON runs (wake_key) WHERE wake_key IS NOT NULL",

    # checkpoints — append-only resumption cursors, one row per save.
    # PK (run_id, seq) makes a duplicate sequence number a constraint
    # error rather than a silently lost checkpoint.
    """CREATE TABLE IF NOT EXISTS checkpoints (
        run_id      TEXT NOT NULL,
        seq         INTEGER NOT NULL,
        cursor_json TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        PRIMARY KEY (run_id, seq)
    )""",

    # effects — at-most-once ledger for authoritative side effects.
    # The PK on key is the claim: a second claim of a live key is a
    # constraint error, which is how duplicate sends are prevented
    # even when two processes race.
    """CREATE TABLE IF NOT EXISTS effects (
        key          TEXT PRIMARY KEY,
        action       TEXT NOT NULL,
        status       TEXT NOT NULL,
        result_json  TEXT,
        run_id       TEXT,
        claimed_at   TEXT NOT NULL,
        completed_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_effects_status ON effects (status, claimed_at)",

    # ── Cognitive architecture (v5) ──────────────────────────────────
    # claims — propositions with explicit epistemic provenance
    """CREATE TABLE IF NOT EXISTS claims (
        id            TEXT PRIMARY KEY,
        subject       TEXT NOT NULL,
        predicate     TEXT NOT NULL,
        value         TEXT NOT NULL,
        provenance    TEXT NOT NULL,
        source_id     TEXT NOT NULL DEFAULT 'user',
        confidence    REAL NOT NULL DEFAULT 1.0,
        status        TEXT NOT NULL DEFAULT 'valid',
        valid_from    TEXT,
        valid_until   TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_claims_subject_pred ON claims (subject, predicate, status)",
    "CREATE INDEX IF NOT EXISTS idx_claims_provenance ON claims (provenance)",
    "CREATE INDEX IF NOT EXISTS idx_claims_created ON claims (created_at)",

    # beliefs before evidence so the belief_id FK has a table to name
    """CREATE TABLE IF NOT EXISTS beliefs (
        id                TEXT PRIMARY KEY,
        subject           TEXT NOT NULL,
        predicate         TEXT NOT NULL,
        value             TEXT NOT NULL,
        confidence        REAL NOT NULL DEFAULT 1.0,
        status            TEXT NOT NULL DEFAULT 'active',
        valid_from        TEXT,
        valid_until       TEXT,
        superseded_by     TEXT,
        evidence_ids_json TEXT NOT NULL DEFAULT '[]',
        created_at        TEXT NOT NULL,
        updated_at        TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_beliefs_subject_pred ON beliefs (subject, predicate, status)",
    "CREATE INDEX IF NOT EXISTS idx_beliefs_status ON beliefs (status, updated_at)",

    # evidence — links tying claims/beliefs to turns, tool executions, or documents
    """CREATE TABLE IF NOT EXISTS evidence (
        id           TEXT PRIMARY KEY,
        claim_id     TEXT REFERENCES claims(id) ON DELETE CASCADE,
        belief_id    TEXT REFERENCES beliefs(id) ON DELETE CASCADE,
        event_id     TEXT,
        source_type  TEXT NOT NULL DEFAULT 'turn',
        snippet      TEXT NOT NULL DEFAULT '',
        uri          TEXT,
        created_at   TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence (claim_id)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_belief ON evidence (belief_id)",

    # entities — structured world model actors, tools, workspaces
    """CREATE TABLE IF NOT EXISTS entities (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        kind            TEXT NOT NULL DEFAULT 'concept',
        aliases_json    TEXT NOT NULL DEFAULT '[]',
        attributes_json TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (name)",
    "CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities (kind)",

    # relationships — typed directed connections between entities
    """CREATE TABLE IF NOT EXISTS relationships (
        id             TEXT PRIMARY KEY,
        source_entity  TEXT NOT NULL,
        target_entity  TEXT NOT NULL,
        relation_type  TEXT NOT NULL,
        confidence     REAL NOT NULL DEFAULT 1.0,
        valid_from     TEXT,
        valid_until    TEXT,
        metadata_json  TEXT NOT NULL DEFAULT '{}',
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_relationships_st ON relationships (source_entity, target_entity)",
    "CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships (relation_type)",
)


def _migrate_facts_table(conn: sqlite3.Connection) -> None:
    """Rebuild an older ``facts`` table into the v2 shape (subject / source /
    tags / note + composite PK ``(subject, key, source)``). Idempotent: a
    no-op on a fresh DB (no table yet) or one already at v2. Existing rows
    become subject='user', source='user'. Runs before the schema CREATE
    INDEXes that reference the new columns.

    Does not begin or commit a transaction — the caller
    (``_ensure_schema``) wraps apply + version stamp in one
    ``BEGIN IMMEDIATE`` so a failure cannot leave v2 tables wearing a
    v1 label, or the reverse. ``executescript`` is deliberately not used:
    the stdlib issues a COMMIT before running the script, which would
    split the stamp from the change.
    """
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
    conn.execute("DROP TABLE IF EXISTS _facts_v2")
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        f"""
        INSERT OR IGNORE INTO _facts_v2
            (subject, key, value, category, source, tags, note, created_at, updated_at)
            SELECT {subj}, key, value, category, {src}, {tg}, {nt},
                   created_at, updated_at
            FROM facts
        """
    )
    # Seed the history log so migrated facts are traceable from day
    # one (recall_history must not return empty for a fact that
    # demonstrably existed). fact_log may not exist yet — this
    # migration runs BEFORE the schema statements.
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
        INSERT INTO fact_log
            (subject, key, value, category, source, tags, note, ts)
            SELECT subject, key, value, category, source, tags,
                   'migrated from schema v1', updated_at
            FROM _facts_v2
        """
    )
    conn.execute("DROP TABLE facts")
    conn.execute("ALTER TABLE _facts_v2 RENAME TO facts")


# Ordered migrations, keyed by the version they PRODUCE. A database at
# version N-1 reaches N by running MIGRATIONS[N] and only then recording N.
#
# This replaces a branch that did the opposite: an older database had its
# version row UPDATEd straight to SCHEMA_VERSION with no transformation run,
# so a v1 store came out labelled v2 while still holding v1 tables. Every
# later reader then trusted a version number that described a shape the
# database did not have — the failure mode a version stamp exists to prevent.
#
# The invariant, stated so it survives the next edit: THE RECORDED VERSION
# MUST NAME THE SCHEMA THAT ACTUALLY RAN. A step with no migration is a hard
# error, not something to paper over by advancing the number.
def _migrate_commitments(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS commitments (
            id            TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            state         TEXT NOT NULL,
            kind          TEXT NOT NULL DEFAULT 'goal',
            payload_json  TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_commitments_state "
        "ON commitments (state, updated_at)"
    )


def _migrate_runtime(conn: sqlite3.Connection) -> None:
    """v4 — the durable execution layer: runs, checkpoints, effects.

    A v3 database has commitments (what the SI intends) but no record of
    the attempts to discharge them, so a crash lost the attempt entirely.
    This step adds the three tables that survive it, plus ``parent_id``
    on commitments for goal nesting.

    Additive only: no existing row is read, rewritten or dropped, so the
    downgrade path is "ignore these tables" rather than a restore.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id            TEXT PRIMARY KEY,
            commitment_id TEXT NOT NULL,
            state         TEXT NOT NULL,
            attempt       INTEGER NOT NULL DEFAULT 1,
            owner_pid     INTEGER,
            heartbeat_at  TEXT,
            wake_key      TEXT,
            provider      TEXT,
            reason        TEXT,
            payload_json  TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            run_id      TEXT NOT NULL,
            seq         INTEGER NOT NULL,
            cursor_json TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (run_id, seq)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS effects (
            key          TEXT PRIMARY KEY,
            action       TEXT NOT NULL,
            status       TEXT NOT NULL,
            result_json  TEXT,
            run_id       TEXT,
            claimed_at   TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    # ALTER TABLE ADD COLUMN has no IF NOT EXISTS before SQLite 3.35 and
    # errors on a re-run either way, so the column is probed first. The
    # commitments table may not exist yet on a database that reached here
    # without ever opening v3 statements; CREATE ... IF NOT EXISTS above
    # does not cover it, so guard on presence rather than assuming.
    has_commitments = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='commitments'"
    ).fetchone()
    if has_commitments:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(commitments)").fetchall()
        }
        if "parent_id" not in columns:
            conn.execute("ALTER TABLE commitments ADD COLUMN parent_id TEXT")


def _migrate_knowledge(conn: sqlite3.Connection) -> None:
    """v5 — epistemic knowledge: claims, beliefs, evidence, entities, relationships.

    v4 recorded what the SI did. v5 records what it knows, and *how* it
    knows it. Additive only: no existing row is read, rewritten or dropped.
    Beliefs are created before evidence so the belief_id FK names a table
    that already exists.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS claims (
            id            TEXT PRIMARY KEY,
            subject       TEXT NOT NULL,
            predicate     TEXT NOT NULL,
            value         TEXT NOT NULL,
            provenance    TEXT NOT NULL,
            source_id     TEXT NOT NULL DEFAULT 'user',
            confidence    REAL NOT NULL DEFAULT 1.0,
            status        TEXT NOT NULL DEFAULT 'valid',
            valid_from    TEXT,
            valid_until   TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_claims_subject_pred "
        "ON claims (subject, predicate, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_claims_provenance ON claims (provenance)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_claims_created ON claims (created_at)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS beliefs (
            id                TEXT PRIMARY KEY,
            subject           TEXT NOT NULL,
            predicate         TEXT NOT NULL,
            value             TEXT NOT NULL,
            confidence        REAL NOT NULL DEFAULT 1.0,
            status            TEXT NOT NULL DEFAULT 'active',
            valid_from        TEXT,
            valid_until       TEXT,
            superseded_by     TEXT,
            evidence_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_beliefs_subject_pred "
        "ON beliefs (subject, predicate, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_beliefs_status "
        "ON beliefs (status, updated_at)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence (
            id           TEXT PRIMARY KEY,
            claim_id     TEXT REFERENCES claims(id) ON DELETE CASCADE,
            belief_id    TEXT REFERENCES beliefs(id) ON DELETE CASCADE,
            event_id     TEXT,
            source_type  TEXT NOT NULL DEFAULT 'turn',
            snippet      TEXT NOT NULL DEFAULT '',
            uri          TEXT,
            created_at   TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_claim ON evidence (claim_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_belief ON evidence (belief_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            kind            TEXT NOT NULL DEFAULT 'concept',
            aliases_json    TEXT NOT NULL DEFAULT '[]',
            attributes_json TEXT NOT NULL DEFAULT '{}',
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities (kind)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS relationships (
            id             TEXT PRIMARY KEY,
            source_entity  TEXT NOT NULL,
            target_entity  TEXT NOT NULL,
            relation_type  TEXT NOT NULL,
            confidence     REAL NOT NULL DEFAULT 1.0,
            valid_from     TEXT,
            valid_until    TEXT,
            metadata_json  TEXT NOT NULL DEFAULT '{}',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relationships_st "
        "ON relationships (source_entity, target_entity)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_relationships_type "
        "ON relationships (relation_type)"
    )


_MIGRATIONS: dict[int, tuple[str, Callable[[sqlite3.Connection], None]]] = {
    2: ("facts-subject-source-tags-note", lambda conn: _migrate_facts_table(conn)),
    3: ("commitments", _migrate_commitments),
    4: ("runtime-runs-checkpoints-effects", _migrate_runtime),
    5: ("cognitive-knowledge-foundation", _migrate_knowledge),
}


def _record_schema_version(conn: sqlite3.Connection, version: int, now: str) -> None:
    """Write the version row, inserting it if this database predates it."""
    updated = conn.execute(
        "UPDATE schema_version SET version = ?, updated_at = ? WHERE id = 1",
        (version, now),
    ).rowcount
    if not updated:
        conn.execute(
            "INSERT INTO schema_version (id, version, created_at, updated_at) "
            "VALUES (1, ?, ?, ?)",
            (version, now, now),
        )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create / migrate the schema to ``SCHEMA_VERSION``.

    First open: every CREATE TABLE runs cleanly (IF NOT EXISTS) and the
    version row is written at the target — a database built from the current
    statements IS the current schema, so there is nothing to migrate.

    Same-version reopen: the CREATE statements no-op and the version matches,
    so this returns without touching anything. That idempotence is what makes
    it safe on every open.

    Older database: each pending migration runs IN ITS OWN TRANSACTION, and
    the new version is recorded inside that same transaction. A failure rolls
    back the step and the stamp together, leaving the database coherent at the
    last version that genuinely completed — so a retry resumes there instead
    of skipping the step that failed.

    Newer database: refused. Writing an old shape over a newer one is not
    recoverable; stopping is.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # The version row lives in a table the schema statements create, so on a
    # database that predates it we have to make the table before we can ask.
    # CREATE TABLE IF NOT EXISTS is safe on every path.
    conn.execute(_SCHEMA_STATEMENTS[0])
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    current = int(row["version"]) if row is not None else None

    if current is not None and current > SCHEMA_VERSION:
        raise RuntimeError(
            f"state.db schema is v{current} but installed core knows "
            f"only v{SCHEMA_VERSION} — upgrade the framework."
        )

    if current is None:
        # No version row. Either a brand-new database, or one written before
        # versioning existed. They are distinguishable: a pre-versioning store
        # already has a `facts` table, a new one does not.
        legacy = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='facts'"
        ).fetchone()
        current = 1 if legacy else SCHEMA_VERSION
        if not legacy:
            # Fresh: build the current shape and record it as such.
            conn.executescript("BEGIN; " + "; ".join(_SCHEMA_STATEMENTS) + "; COMMIT;")
            _record_schema_version(conn, SCHEMA_VERSION, now)
            conn.commit()
            return
        _record_schema_version(conn, current, now)
        conn.commit()

    for version in range(current + 1, SCHEMA_VERSION + 1):
        step = _MIGRATIONS.get(version)
        if step is None:
            raise RuntimeError(
                f"state.db is at v{current} and this build targets "
                f"v{SCHEMA_VERSION}, but no migration is registered for v{version}. "
                "Refusing to advance the recorded version without running one."
            )
        name, apply = step
        try:
            # Close an implicit transaction so BEGIN IMMEDIATE is legal on
            # both production (isolation_level=None) and default-isolation
            # connections. executescript is not used here: it COMMITs first.
            with contextlib.suppress(sqlite3.Error):
                conn.execute("COMMIT")
            conn.execute("BEGIN IMMEDIATE")
            apply(conn)
            # The version is recorded in the SAME transaction as the change
            # it describes, so the two can never disagree.
            _record_schema_version(conn, version, now)
            conn.execute("COMMIT")
        except Exception as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise RuntimeError(
                f"state.db migration to v{version} ({name}) failed: {exc}. "
                f"The database is unchanged at v{current}."
            ) from exc
        current = version

    # Bring indexes and any newly added tables into being once the shape is
    # right — v2 indexes reference columns a v1 table lacked, which is why
    # this runs after the migrations rather than before them.
    conn.executescript("BEGIN; " + "; ".join(_SCHEMA_STATEMENTS) + "; COMMIT;")
    _record_schema_version(conn, SCHEMA_VERSION, now)
    conn.commit()


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
