"""v3 → v4 on a database built the way a v3 release actually built one.

The migration adds tables and one column. That makes it low-risk, not
no-risk: the failure everyone regrets is the one that advanced the
version stamp without running the step, so the data is checked before
and after rather than assumed.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store


V3_SCHEMA = """
CREATE TABLE schema_version (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    version   INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE facts (
    subject    TEXT NOT NULL DEFAULT 'user',
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'general',
    source     TEXT NOT NULL DEFAULT 'user',
    tags       TEXT,
    note       TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (subject, key, source)
);
CREATE TABLE commitments (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    state         TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'goal',
    payload_json  TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
INSERT INTO schema_version VALUES (1, 3, '2026-01-01T00:00:00+00:00',
                                      '2026-01-01T00:00:00+00:00');
INSERT INTO facts (subject, key, value) VALUES ('user', 'name', 'Matthew');
INSERT INTO commitments VALUES ('c-old-1', 'finish the archive', 'active',
    'goal', '{"note": "pre-existing"}', '2026-01-01T00:00:00+00:00',
    '2026-01-02T00:00:00+00:00');
"""


@pytest.fixture
def v3_db(tmp_path):
    """A state.db exactly as a v3 build left it."""
    path = tmp_path / "state.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(V3_SCHEMA)
    conn.commit()
    conn.close()
    return tmp_path


def _version(tmp_path) -> int:
    conn = sqlite3.connect(str(tmp_path / "state.db"))
    try:
        return int(conn.execute(
            "SELECT version FROM schema_version WHERE id = 1"
        ).fetchone()[0])
    finally:
        conn.close()


def test_fixture_really_is_v3(v3_db):
    assert _version(v3_db) == 3


def test_open_upgrades_to_v4(v3_db):
    sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
    sqlite_store.close()
    assert _version(v3_db) == sqlite_store.SCHEMA_VERSION == 4


def test_existing_rows_survive_the_upgrade(v3_db):
    sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
    try:
        conn = sqlite_store.connection()
        fact = conn.execute(
            "SELECT value FROM facts WHERE key = 'name'"
        ).fetchone()
        assert fact["value"] == "Matthew"

        commitment = SqliteCommitmentStore().get("c-old-1")
        assert commitment.title == "finish the archive"
        assert commitment.state == "active"
        assert commitment.payload == {"note": "pre-existing"}
        assert commitment.parent_id is None
    finally:
        sqlite_store.close()


def test_migrated_database_runs_the_new_runtime(v3_db):
    """The upgrade is only real if the new layer works on the old data."""
    sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
    try:
        runs = SqliteRunStore()
        run = runs.create("c-old-1", provider="claude", owner_pid=4242)
        runs.transition(run.id, "active")
        runs.checkpoint(run.id, {"processed": 5})

        recovered = runs.recover(is_alive=lambda pid: False)
        assert [r.id for r in recovered] == [run.id]

        _, checkpoint = runs.resume(run.id)
        assert checkpoint.cursor == {"processed": 5}
    finally:
        sqlite_store.close()


def test_pre_existing_commitment_can_adopt_children_after_upgrade(v3_db):
    sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
    try:
        store = SqliteCommitmentStore()
        child = store.create("sub-task", parent_id="c-old-1")
        assert [c.id for c in store.children("c-old-1")] == [child.id]
    finally:
        sqlite_store.close()


def test_upgrade_is_idempotent(v3_db):
    for _ in range(3):
        sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
        sqlite_store.close()
    assert _version(v3_db) == 4

    sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
    try:
        columns = [
            row["name"] for row in
            sqlite_store.connection().execute("PRAGMA table_info(commitments)")
        ]
        assert columns.count("parent_id") == 1
    finally:
        sqlite_store.close()


def test_a_newer_database_is_refused_not_downgraded(tmp_path):
    path = tmp_path / "state.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(V3_SCHEMA)
    conn.execute("UPDATE schema_version SET version = 99 WHERE id = 1")
    conn.commit()
    conn.close()

    with pytest.raises(RuntimeError, match="upgrade the framework"):
        sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    sqlite_store.close()


def test_v4_tables_exist_after_upgrade(v3_db):
    sqlite_store.bind(SimpleNamespace(memory_dir=v3_db))
    try:
        names = {
            row["name"] for row in sqlite_store.connection().execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"runs", "checkpoints", "effects"} <= names
    finally:
        sqlite_store.close()


def test_the_migration_step_does_the_work_itself(v3_db):
    """Guard against a hollow migration.

    ``_ensure_schema`` re-runs the full CREATE-IF-NOT-EXISTS block after
    migrating, so every assertion above would still pass if the v4 step
    were an empty function — and the recorded version would then name a
    schema the step did not produce, which is the exact failure the
    ordered-migrations comment in the store warns about. So call the
    step on its own and check it, alone, is sufficient.
    """
    conn = sqlite3.connect(str(v3_db / "state.db"))
    conn.row_factory = sqlite3.Row
    try:
        sqlite_store._migrate_runtime(conn)

        names = {
            row["name"] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert {"runs", "checkpoints", "effects"} <= names

        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(commitments)")
        }
        assert "parent_id" in columns
    finally:
        conn.close()


def test_the_migration_step_is_safe_to_re_run(v3_db):
    """ALTER TABLE ADD COLUMN is not idempotent on its own."""
    conn = sqlite3.connect(str(v3_db / "state.db"))
    conn.row_factory = sqlite3.Row
    try:
        sqlite_store._migrate_runtime(conn)
        sqlite_store._migrate_runtime(conn)  # must not raise
    finally:
        conn.close()
