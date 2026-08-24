"""Schema migration v5 — knowledge tables on top of the v4 runtime layer.

v4 (Agent 1) added runs / checkpoints / effects. v5 (Agent 2) adds
claims / beliefs / evidence / entities / relationships. These tests
assert both directions that matter:

  - a pre-v4 database still reaches the current schema, keeps its rows,
    and gains both the runtime and knowledge tables;
  - a v4 (runtime-only) database gains knowledge tables without losing
    runs or commitments.

The v4 step itself is covered in
``packages/jaeger-agent/tests/runtime/test_schema_v4_migration.py``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from jaeger_agent.memory import sqlite_store as store
from jaeger_agent.memory.models import (
    Belief,
    Claim,
    Entity,
    ProvenanceKind,
)
from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore


KNOWLEDGE_TABLES = {"claims", "evidence", "beliefs", "entities", "relationships"}
RUNTIME_TABLES = {"runs", "checkpoints", "effects"}


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _version(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return int(conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()[0])
    finally:
        conn.close()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _make_v1_database(path: Path) -> None:
    conn = _open(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO schema_version VALUES (1, 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        CREATE TABLE facts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO facts VALUES ('theme', 'dark', 'preferences', '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        INSERT INTO facts VALUES ('language', 'python', 'skills', '2026-01-01T00:00:00', '2026-01-01T00:00:00');
        """
    )
    conn.close()


def _make_v3_database(path: Path) -> None:
    conn = _open(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO schema_version VALUES (1, 3, '2026-06-01T00:00:00', '2026-06-01T00:00:00');
        CREATE TABLE facts (
            subject TEXT NOT NULL DEFAULT 'user',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            source TEXT NOT NULL DEFAULT 'user',
            tags TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (subject, key, source)
        );
        INSERT INTO facts VALUES ('user', 'workspace', 'ARES', 'general', 'user', '', '', '2026-06-01T00:00:00', '2026-06-01T00:00:00');
        CREATE TABLE commitments (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            state TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'goal',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO commitments VALUES ('goal-1', 'Build SI', 'active', 'goal', '{}', '2026-06-01T00:00:00', '2026-06-01T00:00:00');
        """
    )
    conn.close()


def _make_v4_database(path: Path) -> None:
    """A database as Agent 1 left it: runtime tables, no knowledge tables."""
    conn = _open(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO schema_version VALUES (1, 4, '2026-08-23T00:00:00', '2026-08-23T00:00:00');
        CREATE TABLE facts (
            subject TEXT NOT NULL DEFAULT 'user',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            source TEXT NOT NULL DEFAULT 'user',
            tags TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (subject, key, source)
        );
        INSERT INTO facts VALUES ('user', 'workspace', 'ARES', 'general', 'user', '', '', '2026-08-23T00:00:00', '2026-08-23T00:00:00');
        CREATE TABLE commitments (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            state TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'goal',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            parent_id TEXT
        );
        INSERT INTO commitments VALUES ('goal-1', 'Build SI', 'active', 'goal', '{}', '2026-08-23T00:00:00', '2026-08-23T00:00:00', NULL);
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            commitment_id TEXT NOT NULL,
            state TEXT NOT NULL,
            attempt INTEGER NOT NULL DEFAULT 1,
            owner_pid INTEGER,
            heartbeat_at TEXT,
            wake_key TEXT,
            provider TEXT,
            reason TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO runs VALUES (
            'run-1', 'goal-1', 'blocked', 1, NULL, NULL, NULL, 'claude',
            'owner_lost', '{}', '2026-08-23T00:00:00', '2026-08-23T00:00:00'
        );
        CREATE TABLE checkpoints (
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            cursor_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, seq)
        );
        INSERT INTO checkpoints VALUES ('run-1', 1, '{"processed": 3}', '2026-08-23T00:00:00');
        CREATE TABLE effects (
            key TEXT PRIMARY KEY,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            run_id TEXT,
            claimed_at TEXT NOT NULL,
            completed_at TEXT
        );
        INSERT INTO effects VALUES (
            'mail:welcome', 'send_email', 'completed', '{"ok": true}',
            'run-1', '2026-08-23T00:00:00', '2026-08-23T00:00:00'
        );
        """
    )
    conn.close()


def test_v1_to_v5_full_upgrade(tmp_path):
    db_path = tmp_path / "state.db"
    _make_v1_database(db_path)

    conn = _open(db_path)
    try:
        store._ensure_schema(conn)
        assert int(conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()["version"]) == 5

        facts = conn.execute(
            "SELECT subject, key, value, source FROM facts ORDER BY key"
        ).fetchall()
        assert len(facts) == 2
        assert tuple(facts[0]) == ("user", "language", "python", "user")
        assert tuple(facts[1]) == ("user", "theme", "dark", "user")

        tables = _tables(conn)
        assert KNOWLEDGE_TABLES <= tables
        assert RUNTIME_TABLES <= tables
        assert "commitments" in tables
    finally:
        conn.close()


def test_v3_to_v5_preserves_commitments_and_enables_knowledge(tmp_path):
    db_path = tmp_path / "state.db"
    _make_v3_database(db_path)

    layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path)
    store.bind(layout)
    try:
        kstore = SqliteKnowledgeStore()

        conn = store.connection()
        c_row = conn.execute(
            "SELECT title, state FROM commitments WHERE id = 'goal-1'"
        ).fetchone()
        assert c_row["title"] == "Build SI"
        assert c_row["state"] == "active"
        assert kstore.recall("workspace") == "ARES"

        tables = _tables(conn)
        assert KNOWLEDGE_TABLES <= tables
        assert RUNTIME_TABLES <= tables

        claim = Claim.create("ARES", "architecture", "modular", ProvenanceKind.INFERRED)
        kstore.add_claim(claim)
        assert kstore.get_claim(claim.id).value == "modular"

        belief = Belief.create("ARES", "status", "production-ready")
        kstore.save_belief(belief)
        assert kstore.get_active_belief("ARES", "status").value == "production-ready"

        entity = Entity.create("JaegerAI", kind="runtime")
        kstore.save_entity(entity)
        assert kstore.find_entity("JaegerAI") is not None
    finally:
        store.close()


def test_v4_to_v5_preserves_runtime_rows(tmp_path):
    """A database Agent 1 already migrated must not lose runs on v5."""
    db_path = tmp_path / "state.db"
    _make_v4_database(db_path)
    assert _version(db_path) == 4

    layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path)
    store.bind(layout)
    try:
        conn = store.connection()
        assert int(conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()["version"]) == store.SCHEMA_VERSION == 5

        run = conn.execute(
            "SELECT state, reason FROM runs WHERE id = 'run-1'"
        ).fetchone()
        assert run["state"] == "blocked"
        assert run["reason"] == "owner_lost"

        checkpoint = conn.execute(
            "SELECT cursor_json FROM checkpoints WHERE run_id = 'run-1' AND seq = 1"
        ).fetchone()
        assert checkpoint["cursor_json"] == '{"processed": 3}'

        effect = conn.execute(
            "SELECT status FROM effects WHERE key = 'mail:welcome'"
        ).fetchone()
        assert effect["status"] == "completed"

        tables = _tables(conn)
        assert KNOWLEDGE_TABLES <= tables

        kstore = SqliteKnowledgeStore()
        claim = Claim.create("user", "shell", "zsh", ProvenanceKind.TOLD)
        kstore.add_claim(claim)
        assert kstore.get_claim(claim.id).value == "zsh"
    finally:
        store.close()


def test_knowledge_migration_step_does_the_work_itself(tmp_path):
    """Guard against a hollow v5 step that only the CREATE-IF-NOT-EXISTS
    post-pass would paper over."""
    db_path = tmp_path / "state.db"
    _make_v4_database(db_path)
    conn = _open(db_path)
    try:
        store._migrate_knowledge(conn)
        assert KNOWLEDGE_TABLES <= _tables(conn)
        store._migrate_knowledge(conn)  # must not raise
    finally:
        conn.close()
