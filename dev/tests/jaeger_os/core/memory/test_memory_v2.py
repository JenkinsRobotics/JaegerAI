"""Memory schema v2 — the paths the 2026-07-03 redesign added.

Covers what the quality review flagged as untested: the v1→v2 facts
rebuild, source isolation (benchmark facts never surface as the
operator's), recall precedence across sources, the fact_log history,
subject scoping in list_facts, the hermetic snapshot's SQLite handling,
and the bench's memory-source guard.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_os.core.memory import memory as mem
from jaeger_os.core.memory import sqlite_store


@pytest.fixture()
def layout(tmp_path):
    lay = SimpleNamespace(root=tmp_path, memory_dir=tmp_path / "memory")
    lay.memory_dir.mkdir(parents=True)
    yield lay
    sqlite_store.close()


@pytest.fixture()
def bound(layout):
    sqlite_store.bind(layout)
    mem.set_memory_source("user")
    yield layout
    mem.set_memory_source("user")
    sqlite_store.close()


# ── v1 → v2 migration ──────────────────────────────────────────────


def _make_v1_db(memory_dir: Path) -> None:
    """Build a genuine v1-shape state.db (key-only PK, no subject/source)."""
    conn = sqlite3.connect(str(memory_dir / "state.db"))
    conn.executescript(
        """
        CREATE TABLE schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO schema_version VALUES (1, 1, 't0', 't0');
        CREATE TABLE facts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO facts VALUES
            ('favorite_color', 'teal', 'preferences', 't0', 't0'),
            ('hometown', 'Austin', 'general', 't0', 't0');
        """
    )
    conn.commit()
    conn.close()


def test_v1_db_migrates_rows_and_shape(layout):
    _make_v1_db(layout.memory_dir)
    sqlite_store.bind(layout)
    conn = sqlite_store.connection()
    info = conn.execute("PRAGMA table_info(facts)").fetchall()
    cols = {r[1] for r in info}
    pk = {r[1] for r in info if r[5]}
    assert {"subject", "source", "tags", "note"} <= cols
    assert pk == {"subject", "key", "source"}
    # rows preserved, defaulted to subject/user source/user
    assert mem.recall("favorite_color") == "teal"
    assert mem.recall("hometown") == "Austin"
    row = conn.execute(
        "SELECT subject, source FROM facts WHERE key='hometown'"
    ).fetchone()
    assert (row["subject"], row["source"]) == ("user", "user")
    # migrated facts are traceable: the rebuild seeds one fact_log row
    # per fact, so recall_history isn't empty for pre-v2 facts.
    hist = mem.recall_history("hometown")
    assert [h["value"] for h in hist] == ["Austin"]
    assert hist[0]["note"] == "migrated from schema v1"


def test_migration_is_idempotent_across_rebinds(layout):
    _make_v1_db(layout.memory_dir)
    sqlite_store.bind(layout)
    assert mem.recall("favorite_color") == "teal"
    sqlite_store.close()
    sqlite_store.bind(layout)          # second open: shape-check no-ops
    assert mem.recall("favorite_color") == "teal"
    assert sqlite_store.connection().execute(
        "SELECT COUNT(*) FROM facts").fetchone()[0] == 2


# ── source isolation + precedence ──────────────────────────────────


def test_benchmark_forget_cannot_delete_operator_facts(bound):
    """Review 2026-07-04 critical: in benchmark mode, forget() reached
    through the source boundary and deleted a live source='user' row the
    bench couldn't even see via recall. Destruction must be source-scoped
    exactly like reads."""
    mem.remember("home_town", "Austin")                   # operator fact
    mem.set_memory_source("benchmark")
    assert mem.forget("home_town") is False               # nothing IT owns
    mem.set_memory_source("user")
    assert mem.recall("home_town") == "Austin"            # survived
    # and symmetrically: operator forget leaves benchmark rows alone
    mem.set_memory_source("benchmark")
    mem.remember("home_town", "Testville")
    mem.set_memory_source("user")
    mem.forget("home_town")
    mem.set_memory_source("benchmark")
    assert mem.recall("home_town") == "Testville"


def test_benchmark_facts_never_surface_as_operator_facts(bound):
    mem.set_memory_source("benchmark")
    mem.remember("favorite_color", "crimson")
    mem.set_memory_source("user")
    assert mem.recall("favorite_color") is None          # excluded
    assert "favorite_color" not in mem.list_facts()      # excluded
    mem.set_memory_source("benchmark")
    assert mem.recall("favorite_color") == "crimson"     # bench sees its own


def test_recall_precedence_user_beats_agent(bound):
    mem.remember("favorite_color", "green", source="agent")
    mem.remember("favorite_color", "blue", source="user")
    assert mem.recall("favorite_color") == "blue"
    # and the fuzzy path honours the same precedence
    assert mem.recall("favorite color") == "blue"


def test_memory_source_guard_restores_on_exception(bound):
    """The bench must restore the live source even when a run raises —
    leaking 'benchmark' hides the operator's real memory."""
    from jaeger_os.core.bench import runner as bench_runner
    from jaeger_os.core.bench.cases import CASES

    def _boom(*a, **k):
        raise RuntimeError("mid-bench crash")

    orig = bench_runner._drive_one
    bench_runner._drive_one = _boom
    try:
        with pytest.raises(RuntimeError):
            bench_runner.run_bench(object(), ids=[CASES[0].id], hermetic=False)
    finally:
        bench_runner._drive_one = orig
    assert mem.current_memory_source() == "user"


# ── history (fact_log) ─────────────────────────────────────────────


def test_recall_history_traces_values_over_time(bound):
    mem.remember("favorite_color", "blue", subject="jonathan", note="day 1")
    mem.remember("favorite_color", "black", subject="jonathan", note="day 2")
    hist = mem.recall_history("favorite_color", subject="jonathan")
    assert [h["value"] for h in hist] == ["blue", "black"]
    assert hist[0]["note"] == "day 1"
    # current view = latest
    assert mem.recall("favorite_color", subject="jonathan") == "black"


def test_forget_keeps_history(bound):
    mem.remember("favorite_color", "blue", subject="jonathan")
    assert mem.forget("favorite_color", subject="jonathan") is True
    assert mem.recall("favorite_color", subject="jonathan") is None
    assert len(mem.recall_history("favorite_color", subject="jonathan")) == 1


# ── subject scoping ────────────────────────────────────────────────


def test_list_facts_is_subject_scoped(bound):
    mem.remember("favorite_color", "blue")                      # operator
    mem.remember("favorite_color", "red", subject="alice")
    assert mem.list_facts()["favorite_color"] == "blue"          # never alice's
    assert mem.list_facts(subject="alice")["favorite_color"] == "red"
    merged = mem.list_facts(subject=None)
    assert merged["favorite_color"] == "blue"
    assert merged["alice:favorite_color"] == "red"               # no clobber
    assert mem.list_facts_by_category()["general"]["favorite_color"] == "blue"


def test_recall_is_subject_scoped(bound):
    mem.remember("favorite_color", "red", subject="alice")
    assert mem.recall("favorite_color") is None                  # operator has none
    assert mem.recall("favorite_color", subject="alice") == "red"


# ── hermetic snapshot: SQLite must roll back AND stay usable ───────


def test_hermetic_rolls_back_sqlite_and_rebinds(bound):
    from jaeger_os.core.bench.runner import _hermetic_memory
    mem.remember("pre_existing", "yes")
    with _hermetic_memory(bound):
        mem.remember("bench_junk", "written during bench")
        assert mem.recall("bench_junk") == "written during bench"
    # bench write rolled back; pre-existing intact; store USABLE after
    assert mem.recall("bench_junk") is None
    assert mem.recall("pre_existing") == "yes"
    mem.remember("post_bench", "still works")
    assert mem.recall("post_bench") == "still works"
