"""SQLite session persistence — conversations survive app close.

Pin: turns are recorded, history round-trips in order, list_sessions ranks
by recency with preview + count, titles set, and an empty store is clean.
"""

from __future__ import annotations

from jaeger_os.core.sessions import SessionStore


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
