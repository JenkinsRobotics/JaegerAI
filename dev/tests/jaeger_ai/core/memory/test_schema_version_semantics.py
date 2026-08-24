"""The recorded schema version must name the schema that actually ran.

Phase 0.5 finding. ``_ensure_schema`` used to end with:

    # Older version → future migration runner.
    conn.execute("UPDATE schema_version SET version = ?, ...")

which advanced an old database's version number without running anything. A v1
store came out labelled v2 while still holding v1 tables, and every later
reader trusted a number describing a shape the database did not have. That is
precisely the failure a version stamp exists to prevent, so it is now a hard
error: a step with no registered migration refuses rather than relabelling.

These cover the states a long-lived store passes through — fresh, legacy,
already-current, reopened, failed mid-migration, and from the future.
"""

from __future__ import annotations

import sqlite3

import pytest

from jaeger_agent.memory import sqlite_store as store


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _version(conn) -> int | None:
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return int(row["version"]) if row else None


def _facts_columns(conn) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(facts)")}


def _make_v1(path) -> None:
    """A pre-v2 store: old ``facts`` shape, real rows, no version row.

    This is what an install that predates versioning actually looks like on
    disk — the shape ``_migrate_facts_table`` detects.
    """
    conn = _open(path)
    conn.executescript(
        """
        CREATE TABLE facts (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT 'general',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO facts (key, value, category, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [("colour", "blue", "general", "t0", "t0"),
         ("city", "leeds", "general", "t0", "t0")],
    )
    conn.commit()
    conn.close()


# ── the ordinary states ────────────────────────────────────────────────


def test_a_fresh_database_is_created_at_the_current_version(tmp_path):
    path = tmp_path / "state.db"
    conn = _open(path)
    try:
        store._ensure_schema(conn)
        assert _version(conn) == store.SCHEMA_VERSION
        assert {"subject", "source", "tags", "note"} <= _facts_columns(conn)
    finally:
        conn.close()


def test_reopening_an_up_to_date_database_changes_nothing(tmp_path):
    """Idempotence is what licenses running this on every open."""
    path = tmp_path / "state.db"
    conn = _open(path)
    try:
        store._ensure_schema(conn)
        conn.execute(
            "INSERT INTO facts (subject, key, value, category, source, tags, note,"
            " created_at, updated_at) VALUES ('user','k','v','general','user','','','t','t')"
        )
        conn.commit()
        for _ in range(3):
            store._ensure_schema(conn)
        assert _version(conn) == store.SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_legacy_database_is_migrated_and_its_rows_survive(tmp_path):
    """The case the old code got wrong: real transformation, then the stamp."""
    path = tmp_path / "state.db"
    _make_v1(path)
    conn = _open(path)
    try:
        store._ensure_schema(conn)

        assert _version(conn) == store.SCHEMA_VERSION
        assert {"subject", "source", "tags", "note"} <= _facts_columns(conn)
        rows = conn.execute(
            "SELECT subject, key, value, source FROM facts ORDER BY key"
        ).fetchall()
        assert [tuple(r) for r in rows] == [
            ("user", "city", "leeds", "user"),
            ("user", "colour", "blue", "user"),
        ], "legacy rows did not survive the migration"
    finally:
        conn.close()


# ── the states that used to lie ────────────────────────────────────────


def test_a_missing_migration_refuses_instead_of_relabelling(tmp_path, monkeypatch):
    """The exact regression: no migration for a step must NOT advance the version.

    Simulated by raising the target past what is registered — the same
    situation as a developer bumping SCHEMA_VERSION and forgetting the step.
    """
    path = tmp_path / "state.db"
    conn = _open(path)
    try:
        store._ensure_schema(conn)
        assert _version(conn) == store.SCHEMA_VERSION

        monkeypatch.setattr(store, "SCHEMA_VERSION", store.SCHEMA_VERSION + 1)
        with pytest.raises(RuntimeError, match="no migration is registered"):
            store._ensure_schema(conn)

        # And crucially: the version was NOT moved.
        assert _version(conn) == store.SCHEMA_VERSION - 1
    finally:
        conn.close()


def test_a_failed_migration_leaves_the_recorded_version_behind(tmp_path, monkeypatch):
    """Version and shape must fail together, never separately."""
    path = tmp_path / "state.db"
    _make_v1(path)
    conn = _open(path)
    try:
        def _boom(_conn):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setitem(store._MIGRATIONS, 2, ("facts-boom", _boom))

        with pytest.raises(RuntimeError, match="migration to v2"):
            store._ensure_schema(conn)

        # Still v1, and still the v1 SHAPE — not a v1 table wearing a v2 label.
        assert _version(conn) == 1
        assert "subject" not in _facts_columns(conn)
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2
    finally:
        conn.close()


def test_a_retry_after_a_failure_completes_the_migration(tmp_path, monkeypatch):
    """Recovery: the failed step is re-run, not skipped.

    Without this, "leaves it at v1" could be satisfied by a store that can
    never move forward again.
    """
    path = tmp_path / "state.db"
    _make_v1(path)
    conn = _open(path)
    try:
        def _boom(_conn):
            raise sqlite3.OperationalError("transient")

        monkeypatch.setitem(store._MIGRATIONS, 2, ("facts-boom", _boom))
        with pytest.raises(RuntimeError):
            store._ensure_schema(conn)
        assert _version(conn) == 1

        monkeypatch.undo()          # the transient failure clears
        store._ensure_schema(conn)

        assert _version(conn) == store.SCHEMA_VERSION
        assert {"subject", "source"} <= _facts_columns(conn)
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2
    finally:
        conn.close()


def test_a_database_from_the_future_is_refused(tmp_path):
    """Writing an old shape over a newer one is unrecoverable; refusing is not."""
    path = tmp_path / "state.db"
    conn = _open(path)
    try:
        store._ensure_schema(conn)
        conn.execute(
            "UPDATE schema_version SET version = ? WHERE id = 1",
            (store.SCHEMA_VERSION + 5,),
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="upgrade the framework"):
            store._ensure_schema(conn)

        assert _version(conn) == store.SCHEMA_VERSION + 5
    finally:
        conn.close()


def test_every_version_step_up_to_the_target_has_a_migration():
    """A build whose target outruns its migrations is a packaging error.

    Catching it here means it surfaces in CI rather than on the first operator
    whose database is a version behind.
    """
    missing = [
        version for version in range(2, store.SCHEMA_VERSION + 1)
        if version not in store._MIGRATIONS
    ]
    assert missing == [], (
        f"SCHEMA_VERSION is {store.SCHEMA_VERSION} but no migration is "
        f"registered for {missing}"
    )


def test_a_partially_migrated_database_resumes_from_the_last_completed_step(
    tmp_path, monkeypatch
):
    """v1 → v2 committed, v3 failed: retry starts at v3, not from scratch.

    This is the PARTIAL state: some steps genuinely completed and their
    version numbers were recorded; the failing step rolled back. Re-run
    must not re-apply the committed ones, and must not skip the failed one.
    """
    path = tmp_path / "state.db"
    _make_v1(path)
    conn = _open(path)
    applied: list[int] = []

    def _v2(c):
        applied.append(2)
        store._migrate_facts_table(c)

    def _v3_ok(c):
        applied.append(3)
        c.execute("CREATE TABLE IF NOT EXISTS phase05_partial (id INTEGER)")

    def _v4_boom(_c):
        applied.append(4)
        raise sqlite3.OperationalError("step 4 exploded")

    monkeypatch.setattr(store, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(
        store,
        "_MIGRATIONS",
        {
            2: ("facts-subject-source-tags-note", _v2),
            3: ("partial-probe", _v3_ok),
            4: ("partial-boom", _v4_boom),
        },
    )
    try:
        with pytest.raises(RuntimeError, match="migration to v4"):
            store._ensure_schema(conn)

        assert _version(conn) == 3, "committed steps must keep their stamps"
        assert "phase05_partial" in {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert applied == [2, 3, 4]

        applied.clear()

        def _v4_ok(c):
            applied.append(4)
            c.execute("CREATE TABLE IF NOT EXISTS phase05_recovered (id INTEGER)")

        monkeypatch.setitem(store._MIGRATIONS, 4, ("partial-recovered", _v4_ok))
        store._ensure_schema(conn)

        assert _version(conn) == 4
        assert applied == [4], "retry re-ran the failed step, not the committed ones"
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2
    finally:
        conn.close()


def test_shape_and_version_roll_back_together_when_the_stamp_fails(
    tmp_path, monkeypatch
):
    """A failure after the DDL but before COMMIT must not leave a v2 shape at v1."""
    path = tmp_path / "state.db"
    _make_v1(path)
    conn = _open(path)
    try:
        real_record = store._record_schema_version

        def _boom_on_v2(_conn, version, now):
            if version == 2:
                raise sqlite3.OperationalError("stamp failed")
            return real_record(_conn, version, now)

        monkeypatch.setattr(store, "_record_schema_version", _boom_on_v2)
        with pytest.raises(RuntimeError, match="migration to v2"):
            store._ensure_schema(conn)

        assert _version(conn) is None or _version(conn) == 1
        assert "subject" not in _facts_columns(conn), (
            "v2 columns survived a rolled-back migration"
        )
        assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2
    finally:
        conn.close()
