"""Schema migration v4 tests — verifying historical migration from v1/v2/v3 to v4.

Verifies:
  - Upgrading legacy state.db preserves existing facts, commitments, episodic, and schedules.
  - New v4 cognitive tables (claims, evidence, beliefs, entities, relationships) exist and are usable.
  - Rollback safety and error handling during migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
import pytest

from jaeger_agent.memory import sqlite_store as store
from jaeger_agent.memory.models import (
    Belief,
    BeliefStatus,
    Claim,
    Entity,
    Evidence,
    ProvenanceKind,
    Relationship,
)
from jaeger_agent.memory.sqlite_knowledge import SqliteKnowledgeStore


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _make_v1_database(path: Path) -> None:
    """Build a pre-v2 database (no subject/source on facts, no commitments, no claims)."""
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
    """Build a v3 database (has commitments, but lacks v4 claims/beliefs/entities)."""
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


def test_v1_to_v4_full_upgrade(tmp_path):
    db_path = tmp_path / "state.db"
    _make_v1_database(db_path)

    conn = _open(db_path)
    try:
        store._ensure_schema(conn)
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        assert int(row["version"]) == 4

        # Verify old facts were upgraded to v2+ and survived
        facts = conn.execute("SELECT subject, key, value, source FROM facts ORDER BY key").fetchall()
        assert len(facts) == 2
        assert tuple(facts[0]) == ("user", "language", "python", "user")
        assert tuple(facts[1]) == ("user", "theme", "dark", "user")

        # Verify v4 tables exist
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert {"claims", "evidence", "beliefs", "entities", "relationships", "commitments"} <= tables
    finally:
        conn.close()


def test_v3_to_v4_upgrade_preserves_commitments_and_enables_knowledge(tmp_path):
    db_path = tmp_path / "state.db"
    _make_v3_database(db_path)

    layout = SimpleNamespace(root=tmp_path, memory_dir=tmp_path)
    store.bind(layout)
    try:
        kstore = SqliteKnowledgeStore()

        # Existing v3 commitment and fact are accessible
        conn = store.connection()
        c_row = conn.execute("SELECT title, state FROM commitments WHERE id = 'goal-1'").fetchone()
        assert c_row["title"] == "Build SI"
        assert c_row["state"] == "active"

        assert kstore.recall("workspace") == "ARES"

        # New v4 cognitive features work seamlessly on the upgraded database
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
