"""Clean-slate pruning — opt-in, archived, and refused under a live daemon.

Three failure modes this guards, in descending order of how bad they are:

1. Wiping history the operator still wanted, silently.
2. Writing underneath a running gateway and corrupting the WAL.
3. Pruning as a side effect of ``jaeger onboarding reset``, which §23
   requires stay narrow.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from jaeger_ai.core.gateway import clean_slate as cs


def _store(path, *, sessions: int = 3, owner_pid: int | None = None):
    con = sqlite3.connect(str(path))
    con.execute("create table sessions (id text)")
    con.execute("create table messages (id integer)")
    con.execute("create table schema_meta (k text, v text)")
    con.execute("create table process_lease (owner_pid integer)")
    for index in range(sessions):
        con.execute("insert into sessions values (?)", (f"s{index}",))
        con.execute("insert into messages values (?)", (index,))
    con.execute("insert into schema_meta values ('version', '1')")
    if owner_pid is not None:
        con.execute("insert into process_lease values (?)", (owner_pid,))
    con.commit()
    con.close()
    return path


def _count(path, table):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute(f'select count(*) from "{table}"').fetchone()[0]
    finally:
        con.close()


# ── the live-daemon guard ────────────────────────────────────────────

def test_refuses_while_a_live_daemon_owns_the_store(tmp_path):
    db = _store(tmp_path / "g.sqlite3", owner_pid=os.getpid())   # we are alive
    result = cs.prune_history(db)
    assert not result.ok
    assert str(os.getpid()) in result.refused
    assert _count(db, "sessions") == 3, "history must survive a refusal"


def test_a_stale_lease_from_a_crashed_daemon_does_not_block(tmp_path):
    # pid 1 exists but a nonsense-high pid does not; a crashed daemon must
    # not lock the operator out of their own store forever.
    db = _store(tmp_path / "g.sqlite3", owner_pid=999_999)
    assert cs.live_owner_pid(db) is None
    assert cs.prune_history(db).ok


def test_force_overrides_the_guard(tmp_path):
    db = _store(tmp_path / "g.sqlite3", owner_pid=os.getpid())
    assert cs.prune_history(db, force=True).ok


# ── archive before delete ────────────────────────────────────────────

def test_archives_before_pruning(tmp_path):
    db = _store(tmp_path / "g.sqlite3")
    result = cs.prune_history(db)
    assert result.archived_to is not None
    assert result.archived_to.is_file()
    # The archive still holds what the live store no longer does.
    assert _count(result.archived_to, "sessions") == 3
    assert _count(db, "sessions") == 0


def test_archive_can_be_skipped_explicitly(tmp_path):
    db = _store(tmp_path / "g.sqlite3")
    assert cs.prune_history(db, archive=False).archived_to is None


# ── what is and is not cleared ───────────────────────────────────────

def test_history_tables_are_emptied(tmp_path):
    db = _store(tmp_path / "g.sqlite3")
    result = cs.prune_history(db)
    assert result.removed["sessions"] == 3
    assert result.removed["messages"] == 3
    assert _count(db, "messages") == 0


def test_store_configuration_survives(tmp_path):
    """Emptying schema_meta would corrupt the store, not clear it."""
    db = _store(tmp_path / "g.sqlite3")
    cs.prune_history(db)
    assert _count(db, "schema_meta") == 1
    assert "schema_meta" not in cs.HISTORY_TABLES


def test_missing_database_is_not_an_error(tmp_path):
    result = cs.prune_history(tmp_path / "absent.sqlite3")
    assert result.ok and result.total_removed == 0


def test_pruning_twice_is_safe(tmp_path):
    db = _store(tmp_path / "g.sqlite3")
    cs.prune_history(db)
    assert cs.prune_history(db).total_removed == 0


# ── §23: reset stays narrow unless asked ─────────────────────────────

def test_reset_does_not_prune_without_the_flag(tmp_path, monkeypatch, capsys):
    """The welcome reset must not erase the operator's work by default."""
    from jaeger_ai.cli import onboarding_cmd
    from jaeger_ai.core.instance import first_boot as fb

    root = tmp_path / "inst"
    root.mkdir()
    fb.begin(root)
    monkeypatch.setattr(onboarding_cmd, "_layout", lambda _i: (root, "test"))

    called = {"pruned": False}
    monkeypatch.setattr(onboarding_cmd, "_clean_slate",
                        lambda **_kw: called.__setitem__("pruned", True))

    assert onboarding_cmd.main(["reset", "--yes"]) == 0
    assert called["pruned"] is False, "reset pruned history without --clean-slate"


def test_clean_slate_flag_opts_in(tmp_path, monkeypatch):
    from jaeger_ai.cli import onboarding_cmd
    from jaeger_ai.core.instance import first_boot as fb

    root = tmp_path / "inst"
    root.mkdir()
    fb.begin(root)
    monkeypatch.setattr(onboarding_cmd, "_layout", lambda _i: (root, "test"))

    called = {"pruned": False}
    monkeypatch.setattr(onboarding_cmd, "_clean_slate",
                        lambda **_kw: called.__setitem__("pruned", True))

    assert onboarding_cmd.main(["reset", "--yes", "--clean-slate"]) == 0
    assert called["pruned"] is True
