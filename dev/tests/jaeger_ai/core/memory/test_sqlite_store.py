"""DB-1 — SQLite store foundation tests.

Pin the shape of the schema + the connection lifecycle so DB-2..10
can build on it without worrying about regression at the base.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.memory import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_store():
    """Close the store between tests so each one starts fresh."""
    sqlite_store.close()
    yield
    sqlite_store.close()


@pytest.fixture
def layout(tmp_path):
    """A real layout with the memory dir created — minimum needed
    for ``sqlite_store.bind``."""
    root = tmp_path / "inst"
    root.mkdir()
    layout = InstanceLayout(root=root)
    layout.ensure_dirs()
    return layout


# ── bind / close lifecycle ────────────────────────────────────────


def test_bind_creates_db_file(layout):
    sqlite_store.bind(layout)
    assert sqlite_store.db_path() == layout.memory_dir / "state.db"
    assert sqlite_store.db_path().exists()


def test_bind_is_idempotent_for_same_layout(layout):
    sqlite_store.bind(layout)
    first = sqlite_store.connection()
    sqlite_store.bind(layout)
    second = sqlite_store.connection()
    # Same connection object — bind didn't churn it.
    assert first is second


def test_rebind_to_different_layout_swaps_connection(tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    layout_a = InstanceLayout(root=a)
    layout_a.ensure_dirs()
    sqlite_store.bind(layout_a)
    conn_a = sqlite_store.connection()

    b = tmp_path / "b"
    b.mkdir()
    layout_b = InstanceLayout(root=b)
    layout_b.ensure_dirs()
    sqlite_store.bind(layout_b)
    conn_b = sqlite_store.connection()

    # Different connection objects for different instances.
    assert conn_a is not conn_b
    assert str(sqlite_store.db_path()) == str(layout_b.memory_dir / "state.db")


def test_connection_raises_when_unbound():
    with pytest.raises(RuntimeError, match="not bound"):
        sqlite_store.connection()


def test_close_clears_state(layout):
    sqlite_store.bind(layout)
    assert sqlite_store.is_bound()
    sqlite_store.close()
    assert not sqlite_store.is_bound()
    assert sqlite_store.db_path() is None


# ── schema ────────────────────────────────────────────────────────


_EXPECTED_TABLES = {
    "facts", "episodic", "episodic_embeddings", "schedules",
    "sessions", "tool_calls", "schema_version",
}


def test_schema_creates_all_expected_tables(layout):
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing = _EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing}"


def test_schema_version_row_set_on_first_open(layout):
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == sqlite_store.SCHEMA_VERSION


def test_schema_idempotent_on_reopen(layout):
    """A second bind against the same DB file shouldn't drop / recreate
    tables (would lose data) and shouldn't bump the version stamp."""
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    conn.execute("INSERT INTO facts (key, value, created_at, updated_at) "
                 "VALUES ('k', 'v', 'now', 'now')")
    sqlite_store.close()

    sqlite_store.bind(layout)
    conn2 = sqlite_store.connection()
    row = conn2.execute("SELECT value FROM facts WHERE key='k'").fetchone()
    assert row is not None
    assert row["value"] == "v"


def test_schema_refuses_future_version(layout, monkeypatch):
    """Opening a DB written by a newer framework must refuse, not
    silently downgrade-migrate. Pins the conservative posture."""
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    conn.execute("UPDATE schema_version SET version = 99 WHERE id = 1")
    sqlite_store.close()

    with pytest.raises(RuntimeError, match="schema is v99"):
        sqlite_store.bind(layout)


# ── WAL + production pragmas ──────────────────────────────────────


def test_wal_mode_enabled(layout):
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    # On filesystems that don't support WAL, SQLite reports 'delete'
    # or 'memory' silently. tmp_path is always local, so WAL works.
    assert mode == "wal"


def test_foreign_keys_enabled(layout):
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_busy_timeout_set(layout):
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    # busy_timeout is in milliseconds; production pragma sets 5000.
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


# ── writer() transaction wrapper ──────────────────────────────────


def test_writer_commits_on_success(layout):
    sqlite_store.bind(layout)
    with sqlite_store.writer() as conn:
        conn.execute("INSERT INTO facts (key, value, created_at, updated_at) "
                     "VALUES ('k', 'v', 't', 't')")
    # Commit happened; reader sees the row.
    conn = sqlite_store.connection()
    assert conn.execute("SELECT value FROM facts WHERE key='k'").fetchone()["value"] == "v"


def test_writer_rolls_back_on_exception(layout):
    sqlite_store.bind(layout)
    with pytest.raises(RuntimeError):
        with sqlite_store.writer() as conn:
            conn.execute("INSERT INTO facts (key, value, created_at, updated_at) "
                         "VALUES ('k', 'v', 't', 't')")
            raise RuntimeError("simulated mid-transaction failure")
    # Rollback — the row should NOT be visible.
    conn = sqlite_store.connection()
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_writer_serializes_writes(layout):
    """Two concurrent ``writer()`` blocks must not corrupt the DB;
    the lock serializes them. Smoke against the threading guard."""
    sqlite_store.bind(layout)

    def worker(key: str):
        with sqlite_store.writer() as conn:
            conn.execute(
                "INSERT INTO facts (key, value, created_at, updated_at) "
                "VALUES (?, 'v', 't', 't')", (key,)
            )

    threads = [threading.Thread(target=worker, args=(f"k{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    conn = sqlite_store.connection()
    rows = conn.execute("SELECT key FROM facts ORDER BY key").fetchall()
    assert [r["key"] for r in rows] == [f"k{i}" for i in range(8)]


# ── sqlite-vec extension ──────────────────────────────────────────


def test_has_vec_extension_returns_a_bool(layout):
    """Either True (extension installed + loaded) or False (missing
    or incompatible Python build). Never raises — graceful fallback."""
    sqlite_store.bind(layout)
    assert isinstance(sqlite_store.has_vec_extension(), bool)
