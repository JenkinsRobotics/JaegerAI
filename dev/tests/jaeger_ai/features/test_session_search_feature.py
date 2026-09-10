"""Tests for jaeger_ai.features.session_search."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace

from jaeger_ai.core.sessions import SessionStore, reset_for_tests
from jaeger_ai.features.session_search import (
    open_session_store,
    prepare_search_query,
    sanitize_fts5_query,
    search_messages,
    search_sessions,
    sessions_db_path,
)
from jaeger_ai.features.session_search.fts import fts_enabled
from jaeger_ai.features.session_search.query import escape_like


def test_sanitize_strips_fts_specials_and_caps():
    cleaned = sanitize_fts5_query('hello + world (foo) "exact phrase"')
    assert "exact phrase" in cleaned
    assert "(" not in cleaned.replace('"exact phrase"', "")
    assert len(sanitize_fts5_query("x" * 2000)) <= 600


def test_escape_like_and_prepare():
    assert escape_like("a%b_c") == r"a\%b\_c"
    prepared = prepare_search_query("50% off")
    assert "50" in prepared
    assert prepare_search_query("  chat-send  ")


class _MiniStore:
    """Minimal stand-in so tests do not depend on SessionStore shims."""

    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    preview TEXT,
                    last_active REAL
                );
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                """
            )
            self._conn.execute(
                "INSERT INTO sessions(id, title, preview, last_active) VALUES (?,?,?,?)",
                ("webui:demo", "Demo", "find the zucchini recipe", 1.0),
            )
            self._conn.execute(
                "INSERT INTO messages(session_id, role, text, ts) VALUES (?,?,?,?)",
                ("webui:demo", "user", "find the zucchini recipe", 1.0),
            )

    def list_sessions(self, limit: int = 50):
        cur = self._conn.execute(
            "SELECT id, title, preview FROM sessions ORDER BY last_active DESC LIMIT ?",
            (limit,),
        )
        return [
            {"id": i, "title": t, "preview": p}
            for i, t, p in cur.fetchall()
        ]

    def search(self, query: str, limit: int = 50):
        needle = str(query or "").strip()
        if not needle:
            return self.list_sessions(limit=limit)
        pattern = f"%{escape_like(needle)}%"
        cur = self._conn.execute(
            "SELECT DISTINCT s.id, s.title, s.preview FROM sessions s "
            "LEFT JOIN messages m ON m.session_id=s.id "
            "WHERE s.title LIKE ? ESCAPE '\\' OR s.preview LIKE ? ESCAPE '\\' "
            "OR m.text LIKE ? ESCAPE '\\' ORDER BY s.last_active DESC LIMIT ?",
            (pattern, pattern, pattern, limit),
        )
        return [
            {"id": i, "title": t, "preview": p}
            for i, t, p in cur.fetchall()
        ]


def test_search_sessions_and_messages(tmp_path: Path):
    store = _MiniStore(tmp_path / "sessions.db")
    rows = search_sessions(store, "zucchini", limit=10)
    assert any(r["id"] == "webui:demo" for r in rows)
    hits = search_messages(store, "zucchini", limit=10)
    assert hits and hits[0].session_id == "webui:demo"
    assert "zucchini" in (hits[0].snippet or "").lower()
    assert fts_enabled(store._conn) is False


def test_real_session_store_like_search(tmp_path: Path):
    """DEPTH: search against the real Jaeger sessions.db schema."""
    reset_for_tests()
    layout = SimpleNamespace(memory_dir=tmp_path / "memory")
    layout.memory_dir.mkdir(parents=True)
    assert sessions_db_path(layout) == layout.memory_dir / "sessions.db"

    store = SessionStore(sessions_db_path(layout))
    store.record("abc123def456", "user", "find the zucchini recipe tonight")
    store.record("abc123def456", "assistant", "Here is a roasted zucchini plan.")
    store.set_title("abc123def456", "Dinner ideas")
    store.record("other", "user", "unrelated bridge debug")

    rows = search_sessions(store, "zucchini", limit=10)
    assert [r["id"] for r in rows] == ["abc123def456"]

    hits = search_messages(store, "roasted", limit=10)
    assert hits and hits[0].session_id == "abc123def456"
    assert hits[0].role == "assistant"
    assert "roasted" in (hits[0].snippet or "").lower()

    # Sanitized "%" is stripped for non-CJK LIKE needles — no false positives
    assert search_sessions(store, "zzzz-no-hit", limit=10) == []
    assert fts_enabled(store._conn) is False
    store.close()
    reset_for_tests()


def test_open_session_store_uses_layout(tmp_path: Path, monkeypatch):
    reset_for_tests()
    layout = SimpleNamespace(memory_dir=tmp_path / "memory")
    monkeypatch.setitem(
        __import__("jaeger_ai.main", fromlist=["_pipeline"])._pipeline,
        "layout",
        layout,
    )
    store = open_session_store()
    assert store is not None
    assert sessions_db_path() == layout.memory_dir / "sessions.db"
    reset_for_tests()
