"""F04 — recoverable state migration matrix (RELEASE_AGENT_PROMPT.md M1.3).

All state is synthetic under tmp_path; nothing touches operator state.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest

from jaeger_ai.core.instance import state_migration as sm


class _Crash(BaseException):
    """Simulated process death: not an Exception, so no handler absorbs it."""


def _tree_hashes(root: Path) -> dict[str, str]:
    """Content of every file, excluding SQLite's own -wal/-shm sidecars
    (any reader of a WAL database may create them; content is unaffected)."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.endswith(("-wal", "-shm"))
    }


def _legacy(root: Path) -> Path:
    """A realistic legacy state root: identity, credentials, a WAL database
    with committed-but-uncheckpointed rows, and a nested instance."""
    root.mkdir(parents=True)
    (root / "active_instance").write_text("work\n", encoding="utf-8")
    inst = root / "instances" / "work"
    (inst / "memory").mkdir(parents=True)
    (inst / "identity.yaml").write_text("name: Chosen Name\n", encoding="utf-8")
    creds = inst / "credentials"
    creds.mkdir()
    (creds / "api_key").write_text("SECRET-VALUE", encoding="utf-8")
    os.chmod(creds / "api_key", 0o600)
    db = inst / "memory" / "state.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA user_version=7")
    conn.execute("CREATE TABLE facts (id INTEGER PRIMARY KEY, body TEXT)")
    conn.executemany("INSERT INTO facts (body) VALUES (?)", [(f"fact {i}",) for i in range(50)])
    conn.commit()
    conn.execute("INSERT INTO facts (body) VALUES ('last committed row')")
    conn.commit()
    conn.close()
    return root


def _open_writer_with_wal_only_row(db: Path) -> sqlite3.Connection:
    """Keep a writer open (so nothing checkpoints) holding a committed row
    that exists only in the WAL — the case a byte copy of the .db loses."""
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("INSERT INTO facts (body) VALUES ('only in the WAL')")
    conn.commit()
    return conn


def _rows(db: Path) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        return [r[0] for r in conn.execute("SELECT body FROM facts ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def layout(tmp_path):
    source = _legacy(tmp_path / "home" / ".jaeger_os")
    return source, tmp_path / "home" / ".jaeger_ai"


def test_fresh_install_has_nothing_to_migrate(tmp_path):
    result = sm.migrate_directory(tmp_path / "absent", tmp_path / "dest", kind="t")
    assert result.status == "nothing_to_migrate"
    assert not (tmp_path / "dest").exists()
    assert not sm.work_dir_for(tmp_path / "dest").exists()


def test_legacy_only_migrates_everything_and_leaves_source_intact(layout):
    source, destination = layout
    db = source / "instances" / "work" / "memory" / "state.db"
    writer = _open_writer_with_wal_only_row(db)
    assert (source / "instances/work/memory/state.db-wal").stat().st_size > 0
    before = _tree_hashes(source)
    try:
        result = sm.migrate_directory(source, destination, kind="t")
        # Compared before our writer closes: its close checkpoints the WAL.
        after = _tree_hashes(source)
    finally:
        writer.close()

    assert result.status == "migrated"
    assert after == before, "no source file content changes"
    assert not source.is_symlink()
    inst = destination / "instances" / "work"
    assert (destination / "active_instance").read_text() == "work\n"
    assert (inst / "identity.yaml").read_text() == "name: Chosen Name\n"
    assert (inst / "credentials" / "api_key").read_text() == "SECRET-VALUE"
    assert (inst / "credentials" / "api_key").stat().st_mode & 0o077 == 0
    rows = _rows(inst / "memory" / "state.db")
    assert len(rows) == 52 and rows[-1] == "only in the WAL"
    conn = sqlite3.connect(inst / "memory" / "state.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    conn.close()
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["phase"] == "complete"
    assert "SECRET-VALUE" not in result.manifest_path.read_text()
    assert not (sm.work_dir_for(destination) / "staging").exists()
    assert (sm.work_dir_for(destination) / "backup").is_dir(), "backup retained for the operator"
    assert sm.work_dir_for(destination).parent == destination.parent  # same filesystem


def test_rerun_after_success_is_a_no_op(layout):
    source, destination = layout
    sm.migrate_directory(source, destination, kind="t")
    (destination / "active_instance").write_text("changed after migration\n")

    result = sm.migrate_directory(source, destination, kind="t")

    assert result.status == "already_migrated"
    assert (destination / "active_instance").read_text() == "changed after migration\n"


def test_both_populated_is_a_conflict_and_nothing_moves(layout):
    source, destination = layout
    destination.mkdir()
    (destination / "active_instance").write_text("other\n")
    before = (_tree_hashes(source), _tree_hashes(destination))

    with pytest.raises(sm.MigrationConflict):
        sm.migrate_directory(source, destination, kind="t")

    assert (_tree_hashes(source), _tree_hashes(destination)) == before


def test_empty_destination_placeholder_is_not_a_conflict(layout):
    source, destination = layout
    destination.mkdir()
    assert sm.migrate_directory(source, destination, kind="t").status == "migrated"


def test_legacy_symlink_left_by_the_old_migrator_counts_as_migrated(tmp_path):
    destination = tmp_path / ".jaeger_ai"
    destination.mkdir()
    (tmp_path / ".jaeger_os").symlink_to(destination.name, target_is_directory=True)
    result = sm.migrate_directory(tmp_path / ".jaeger_os", destination, kind="t")
    assert result.status == "already_migrated"


def test_corrupt_database_fails_without_activating_then_recovers(layout):
    source, destination = layout
    db = source / "instances" / "work" / "memory" / "state.db"
    pristine = db.read_bytes()
    db.write_bytes(pristine[:100] + b"\x00" * 4096 + pristine[4196:])

    with pytest.raises(sm.MigrationFailed):
        sm.migrate_directory(source, destination, kind="t")
    assert not destination.exists()

    db.write_bytes(pristine)
    assert sm.migrate_directory(source, destination, kind="t").status == "migrated"


def test_locked_source_database_fails_then_succeeds_when_released(layout, monkeypatch):
    source, destination = layout
    monkeypatch.setattr(sm, "SOURCE_BUSY_TIMEOUT_S", 0.2)
    writer = sqlite3.connect(source / "instances" / "work" / "memory" / "state.db", isolation_level=None)
    writer.execute("PRAGMA locking_mode=EXCLUSIVE")
    writer.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(sm.MigrationFailed):
            sm.migrate_directory(source, destination, kind="t")
        assert not destination.exists()
    finally:
        writer.execute("ROLLBACK")
        writer.close()
    assert sm.migrate_directory(source, destination, kind="t").status == "migrated"


def test_insufficient_space_stops_at_preflight(layout, monkeypatch):
    source, destination = layout
    monkeypatch.setattr(sm.shutil, "disk_usage", lambda path: type("U", (), {"free": 1})())
    with pytest.raises(sm.MigrationFailed, match="free"):
        sm.migrate_directory(source, destination, kind="t")
    assert not destination.exists()


def test_concurrent_migrator_is_excluded(layout):
    source, destination = layout
    work = sm.work_dir_for(destination)
    work.mkdir()
    fd = os.open(work / "lock", os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        with pytest.raises(sm.MigrationBusy):
            sm.migrate_directory(source, destination, kind="t")
    finally:
        os.close(fd)
    assert not destination.exists()


@pytest.mark.parametrize("phase", ["preflight", "lock", "backup", "stage", "verify", "activate", "activated"])
def test_crash_at_every_phase_resumes_to_one_complete_generation(layout, monkeypatch, phase):
    source, destination = layout
    before = _tree_hashes(source)

    def crash(name):
        if name == phase:
            raise _Crash(name)

    monkeypatch.setattr(sm, "_checkpoint", crash)
    with pytest.raises(_Crash):
        sm.migrate_directory(source, destination, kind="t")

    # After the crash: either no destination, or the complete generation.
    if destination.exists():
        assert _rows(destination / "instances" / "work" / "memory" / "state.db")[-1] == "last committed row"

    monkeypatch.setattr(sm, "_checkpoint", lambda name: None)
    result = sm.migrate_directory(source, destination, kind="t")

    assert result.status == "migrated"
    assert json.loads(result.manifest_path.read_text())["phase"] == "complete"
    assert len(_rows(destination / "instances" / "work" / "memory" / "state.db")) == 51
    assert not (sm.work_dir_for(destination) / "staging").exists()
    assert _tree_hashes(source) == before
    assert sm.migrate_directory(source, destination, kind="t").status == "already_migrated"


def test_operator_state_root_migrates_legacy_layout_through_the_engine(tmp_path, monkeypatch):
    from jaeger_ai.core.instance import instance

    _legacy(tmp_path / ".jaeger_os")
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))

    root = instance.operator_state_root()

    assert root == tmp_path.resolve() / ".jaeger_ai"
    assert (root / "active_instance").read_text() == "work\n"
    assert not (tmp_path / ".jaeger_os").is_symlink(), "no compatibility symlink"
    assert instance.operator_state_root() == root


def test_failed_legacy_migration_refuses_to_start(tmp_path, monkeypatch):
    from jaeger_ai.core.instance import instance

    source = _legacy(tmp_path / ".jaeger_os")
    db = source / "instances" / "work" / "memory" / "state.db"
    db.write_bytes(db.read_bytes()[:100] + b"\x00" * 4096)
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))

    with pytest.raises(RuntimeError, match="did not complete"):
        instance.operator_state_root()
    assert not (tmp_path / ".jaeger_ai").exists(), "never start on an empty state root"


def test_active_destination_with_leftover_legacy_dir_keeps_working(tmp_path, monkeypatch):
    """Pre-engine installs can have both: the active ``.jaeger_ai`` and a
    stale ``.jaeger_os``. The active state wins; the leftover is neither
    merged nor deleted."""
    from jaeger_ai.core.instance import instance

    source = _legacy(tmp_path / ".jaeger_os")
    active = tmp_path / ".jaeger_ai"
    active.mkdir()
    (active / "active_instance").write_text("current\n")
    before = _tree_hashes(source)
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))

    assert instance.operator_state_root() == active.resolve()
    assert (active / "active_instance").read_text() == "current\n"
    assert _tree_hashes(source) == before


def test_interrupted_migration_resumes_through_operator_state_root(tmp_path, monkeypatch):
    from jaeger_ai.core.instance import instance

    _legacy(tmp_path / ".jaeger_os")
    monkeypatch.delenv("JAEGER_STATE_DIR", raising=False)
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))

    def crash(name):
        if name == "activated":
            raise _Crash(name)

    monkeypatch.setattr(sm, "_checkpoint", crash)
    with pytest.raises(_Crash):
        instance.operator_state_root()
    monkeypatch.setattr(sm, "_checkpoint", lambda name: None)

    root = instance.operator_state_root()
    manifest = json.loads((sm.work_dir_for(root) / "manifest.json").read_text())
    assert manifest["phase"] == "complete"
