"""DB-2 — facts API now backed by SQLite.

The public API (``remember`` / ``recall`` / ``forget`` /
``list_facts`` / ``list_facts_by_category``) is the same one the
0.1.x JSON store exposed. These tests pin the contract + the
SQL-specific behaviours (timestamps, INSERT-OR-REPLACE,
lazy-import-from-json).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_ai.core.memory import memory as mem
from jaeger_ai.core.memory import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_store():
    sqlite_store.close()
    yield
    sqlite_store.close()


@pytest.fixture
def bound(tmp_path):
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


# ── basic CRUD round-trip ─────────────────────────────────────────


def test_remember_and_recall(bound):
    mem.remember("birthday", "May 15")
    assert mem.recall("birthday") == "May 15"


def test_recall_returns_none_for_missing(bound):
    assert mem.recall("nonexistent") is None


def test_remember_overwrites_value(bound):
    mem.remember("color", "blue")
    mem.remember("color", "green")
    assert mem.recall("color") == "green"


def test_forget_returns_false_when_missing(bound):
    assert mem.forget("never_existed") is False


def test_forget_returns_true_when_present(bound):
    mem.remember("k", "v")
    assert mem.forget("k") is True
    assert mem.recall("k") is None


# ── fuzzy recall (model phrasing drift) ───────────────────────────


def test_recall_substring_match(bound):
    mem.remember("users_birthday", "May 15")
    assert mem.recall("birthday") == "May 15"


def test_recall_word_overlap_fallback(bound):
    mem.remember("favorite_pizza_topping", "pepperoni")
    assert mem.recall("pizza") == "pepperoni"


def test_recall_handles_stopwords(bound):
    """Stopwords ('the', 'my', 'a', etc.) shouldn't drag the word-
    overlap matcher into false matches against any key that
    contains 'the'."""
    mem.remember("favorite_color", "blue")
    mem.remember("my_phone", "555")
    # 'what is my color' → after stopword removal, the only signal
    # is 'color' → matches favorite_color.
    assert mem.recall("what is my color") == "blue"


# ── category handling ────────────────────────────────────────────


def test_category_stored_with_fact(bound):
    mem.remember("alice", "alice@example.com", category="contacts")
    grouped = mem.list_facts_by_category()
    assert grouped == {"contacts": {"alice": "alice@example.com"}}


def test_default_category_is_general(bound):
    mem.remember("note", "anything")
    grouped = mem.list_facts_by_category()
    assert grouped == {"general": {"note": "anything"}}


def test_category_case_normalised(bound):
    mem.remember("k", "v", category="  Contacts  ")
    grouped = mem.list_facts_by_category()
    assert "contacts" in grouped


# ── SQL-specific behaviours ──────────────────────────────────────


def test_facts_table_has_timestamps(bound):
    mem.remember("k", "v")
    conn = sqlite_store.connection()
    row = conn.execute("SELECT created_at, updated_at FROM facts").fetchone()
    assert row["created_at"]
    assert row["updated_at"]
    assert row["created_at"] == row["updated_at"]


def test_overwrite_preserves_created_at(bound):
    mem.remember("k", "v1")
    conn = sqlite_store.connection()
    original_created = conn.execute(
        "SELECT created_at FROM facts WHERE key='k'"
    ).fetchone()["created_at"]

    # Sleep at least the precision boundary so the new updated_at
    # would differ visibly if the row were re-created from scratch.
    import time as _t
    _t.sleep(1.05)
    mem.remember("k", "v2")
    new = conn.execute(
        "SELECT created_at, updated_at FROM facts WHERE key='k'"
    ).fetchone()
    assert new["created_at"] == original_created   # preserved
    assert new["updated_at"] != original_created   # bumped


def test_list_facts_returns_sorted_keys(bound):
    mem.remember("c", "3")
    mem.remember("a", "1")
    mem.remember("b", "2")
    assert list(mem.list_facts().keys()) == ["a", "b", "c"]


# ── lazy import from facts.json ──────────────────────────────────


def test_lazy_import_new_json_shape(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "facts.json").write_text(json.dumps({
        "schema_version": 1,
        "facts": {"birthday": "May 15", "color": "blue"},
        "categories": {"birthday": "personal"},
    }), encoding="utf-8")

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    grouped = mem.list_facts_by_category()
    assert grouped == {
        "personal": {"birthday": "May 15"},
        "general": {"color": "blue"},
    }


def test_lazy_import_legacy_flat_shape(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "facts.json").write_text(
        json.dumps({"old_key": "old_val", "another": "thing"}),
        encoding="utf-8",
    )

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    assert mem.list_facts() == {"old_key": "old_val", "another": "thing"}
    # All land in 'general' because the legacy shape had no categories.
    grouped = mem.list_facts_by_category()
    assert grouped == {"general": {"old_key": "old_val", "another": "thing"}}


def test_lazy_import_skipped_when_sql_already_has_data(tmp_path):
    """Idempotent re-bind: existing SQL rows are NOT overwritten by a
    stale JSON file. Prevents a user who hand-restored data via the
    SQL store from being clobbered by an old JSON sitting alongside."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    # Plant some SQL data first.
    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    mem.remember("from_sql", "this is correct")
    sqlite_store.close()

    # Now plant a stale facts.json
    (mem_dir / "facts.json").write_text(
        json.dumps({"from_sql": "WRONG", "extra": "should-not-land"}),
        encoding="utf-8",
    )
    # Re-bind.
    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    # SQL data wins; JSON not imported.
    assert mem.recall("from_sql") == "this is correct"
    assert mem.recall("extra") is None


def test_lazy_import_handles_missing_or_broken_json(tmp_path):
    """A corrupt facts.json shouldn't crash bind — the agent should
    still boot with an empty SQL table."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    (mem_dir / "facts.json").write_text("{ not valid json", encoding="utf-8")
    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    assert mem.list_facts() == {}
