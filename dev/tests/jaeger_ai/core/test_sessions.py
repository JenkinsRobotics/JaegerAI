"""SQLite session persistence — conversations survive app close.

Pin: turns are recorded, history round-trips in order, list_sessions ranks
by recency with preview + count, titles set, and an empty store is clean.
"""

from __future__ import annotations

from jaeger_ai.core.sessions import SessionStore


def test_record_and_history_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "hello there")
        store.record("s1", "assistant", "hi!")
        store.record("s1", "user", "again")
        hist = store.history("s1")
        assert [(m["role"], m["text"]) for m in hist] == [
            ("user", "hello there"), ("assistant", "hi!"), ("user", "again")]
        assert store.history("nope") == []
    finally:
        store.close()


def test_list_sessions_ranks_by_recency_with_preview(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("old", "user", "first conversation")
        store.record("new", "user", "second conversation")
        rows = store.list_sessions()
        assert [r["id"] for r in rows] == ["new", "old"]   # most-active first
        new = rows[0]
        assert new["preview"] == "second conversation"      # first user line
        assert new["messages"] == 1
    finally:
        store.close()


def test_set_title_and_empty(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        assert store.list_sessions() == []
        store.record("s1", "user", "x")
        store.set_title("s1", "My Task")
        assert store.list_sessions()[0]["title"] == "My Task"
    finally:
        store.close()


def test_list_sessions_carries_created_at(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "hi")
        row = store.list_sessions()[0]
        assert row["created_at"] and row["created_at"] == row["last_active"]
    finally:
        store.close()


def test_prune_drops_oldest_beyond_keep(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        for i in range(5):
            store.record(f"s{i}", "user", f"turn {i}")
        dropped = store.prune(keep=2)
        assert dropped == 3
        remaining = {r["id"] for r in store.list_sessions()}
        assert remaining == {"s3", "s4"}          # most-recently-active 2
        # Messages cascade-deleted with their session.
        assert store.history("s0") == []
        assert store.history("s4") != []
    finally:
        store.close()


def test_prune_zero_keep_is_unlimited_retention(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "x")
        assert store.prune(keep=0) == 0
        assert len(store.list_sessions()) == 1
    finally:
        store.close()


def test_prune_under_the_limit_is_a_noop(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "x")
        assert store.prune(keep=50) == 0
        assert len(store.list_sessions()) == 1
    finally:
        store.close()
