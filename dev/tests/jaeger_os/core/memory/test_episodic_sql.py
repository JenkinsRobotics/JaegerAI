"""DB-3 — episodic table SQL backend.

Pin the contract of ``append_episodic`` + ``load_recent_turns``
against SQLite, plus the lazy-import of legacy ``episodic.jsonl``
on first 0.2.0 bind.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jaeger_os.core.memory import memory as mem
from jaeger_os.core.memory import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_store():
    sqlite_store.close()
    yield
    sqlite_store.close()


@pytest.fixture
def bound(tmp_path):
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


# ── basic round-trip ──────────────────────────────────────────────


def test_append_then_load(bound):
    mem.append_episodic({
        "user": "hi",
        "answer": "hello",
        "decision_raw": "hello",
        "session_key": "default",
    })
    out = mem.load_recent_turns(10)
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_load_returns_empty_when_no_episodes(bound):
    assert mem.load_recent_turns(5) == []


def test_load_n_zero_returns_empty(bound):
    mem.append_episodic({
        "user": "hi", "decision_raw": "hello", "session_key": "default",
    })
    assert mem.load_recent_turns(0) == []


def test_load_respects_chronological_order(bound):
    for i in range(5):
        mem.append_episodic({
            "user": f"q{i}", "decision_raw": f"a{i}",
            "session_key": "default",
        })
    out = mem.load_recent_turns(10)
    # Oldest first — verify q0 leads, q4 last.
    user_contents = [m["content"] for m in out if m["role"] == "user"]
    assert user_contents == ["q0", "q1", "q2", "q3", "q4"]


def test_load_limit_returns_last_n_chronologically(bound):
    for i in range(5):
        mem.append_episodic({
            "user": f"q{i}", "decision_raw": f"a{i}",
            "session_key": "default",
        })
    out = mem.load_recent_turns(2)
    user_contents = [m["content"] for m in out if m["role"] == "user"]
    # The last 2, in chronological order.
    assert user_contents == ["q3", "q4"]


# ── session_key filtering ────────────────────────────────────────


def test_load_filters_by_session_key(bound):
    mem.append_episodic({"user": "tui-q", "decision_raw": "tui-a",
                          "session_key": "tui"})
    mem.append_episodic({"user": "work-q", "decision_raw": "work-a",
                          "session_key": "work"})
    mem.append_episodic({"user": "voice-q", "decision_raw": "voice-a",
                          "session_key": "voice"})

    tui_only = mem.load_recent_turns(10, session_key="tui")
    assert [m["content"] for m in tui_only if m["role"] == "user"] == ["tui-q"]

    work_only = mem.load_recent_turns(10, session_key="work")
    assert [m["content"] for m in work_only if m["role"] == "user"] == ["work-q"]


def test_load_skips_rows_missing_user_or_decision(bound):
    """Defensive: rows without both ``user`` and ``decision_raw``
    can't form a (user, assistant) pair — load_recent_turns skips
    them rather than returning malformed entries."""
    mem.append_episodic({"user": "only_user", "session_key": "default"})
    mem.append_episodic({"decision_raw": "only_answer", "session_key": "default"})
    mem.append_episodic({"user": "q", "decision_raw": "a", "session_key": "default"})
    out = mem.load_recent_turns(10)
    user_contents = [m["content"] for m in out if m["role"] == "user"]
    assert user_contents == ["q"]


# ── schema-aware column extraction ───────────────────────────────


def test_tool_activity_list_persisted_as_json(bound):
    mem.append_episodic({
        "user": "x", "decision_raw": "y", "session_key": "default",
        "tool_activity": ["▸ get_time", "▸ calculate(1+1)"],
    })
    conn = sqlite_store.connection()
    row = conn.execute("SELECT tool_activity FROM episodic").fetchone()
    decoded = json.loads(row["tool_activity"])
    assert decoded == ["▸ get_time", "▸ calculate(1+1)"]


def test_latency_persisted_as_milliseconds(bound):
    mem.append_episodic({
        "user": "x", "decision_raw": "y", "session_key": "default",
        "latency": {"total": 0.42},
    })
    conn = sqlite_store.connection()
    row = conn.execute("SELECT latency_ms FROM episodic").fetchone()
    assert row["latency_ms"] == 420


def test_skipped_final_persisted_as_int_bool(bound):
    mem.append_episodic({
        "user": "x", "decision_raw": "y", "session_key": "default",
        "skipped_final": True,
    })
    conn = sqlite_store.connection()
    row = conn.execute("SELECT skipped_final FROM episodic").fetchone()
    assert row["skipped_final"] == 1


def test_unknown_keys_bundled_into_meta_json(bound):
    """Extra fields (anything the loop adds in the future) land in
    ``meta_json`` so we never lose data even before a schema bump."""
    mem.append_episodic({
        "user": "x", "decision_raw": "y", "session_key": "default",
        "future_field": "hello",
        "extra_thing": {"nested": 42},
    })
    conn = sqlite_store.connection()
    row = conn.execute("SELECT meta_json FROM episodic").fetchone()
    meta = json.loads(row["meta_json"])
    assert meta["future_field"] == "hello"
    assert meta["extra_thing"] == {"nested": 42}


def test_missing_session_key_defaults_to_default(bound):
    mem.append_episodic({"user": "x", "decision_raw": "y"})
    conn = sqlite_store.connection()
    row = conn.execute("SELECT session_key FROM episodic").fetchone()
    assert row["session_key"] == "default"


def test_missing_timestamp_gets_filled_in(bound):
    """A loop that forgets to stamp the entry still gets a valid
    ``ts`` (UTC ISO-8601)."""
    mem.append_episodic({"user": "x", "decision_raw": "y", "session_key": "default"})
    conn = sqlite_store.connection()
    row = conn.execute("SELECT ts FROM episodic").fetchone()
    assert row["ts"]
    # ISO-8601 sanity — parseable by fromisoformat.
    from datetime import datetime
    datetime.fromisoformat(row["ts"])


# ── lazy import from episodic.jsonl ──────────────────────────────


def test_lazy_import_brings_legacy_jsonl_into_sql(tmp_path):
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    # Write a few legacy-shaped rows.
    rows = [
        {"user": "q1", "answer": "a1", "decision_raw": "a1",
         "session_key": "tui", "timestamp": "2026-05-26T10:00:00+00:00"},
        {"user": "q2", "answer": "a2", "decision_raw": "a2",
         "session_key": "tui"},
        {"user": "q3", "answer": "a3", "decision_raw": "a3",
         "session_key": "work"},
    ]
    with (mem_dir / "episodic.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    conn = sqlite_store.connection()
    count = conn.execute("SELECT COUNT(*) FROM episodic").fetchone()[0]
    assert count == 3

    tui_turns = mem.load_recent_turns(10, session_key="tui")
    assert [m["content"] for m in tui_turns if m["role"] == "user"] == ["q1", "q2"]


def test_lazy_import_skipped_when_sql_has_data(tmp_path):
    """Idempotent on re-bind — existing SQL rows take precedence."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    mem.append_episodic({"user": "sql_q", "decision_raw": "sql_a",
                         "session_key": "default"})
    sqlite_store.close()

    # Plant a stale episodic.jsonl
    with (mem_dir / "episodic.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"user": "stale_q", "decision_raw": "stale_a",
                              "session_key": "default"}) + "\n")
    mem.bind(SimpleNamespace(memory_dir=mem_dir))

    # SQL row preserved; JSONL not imported.
    out = mem.load_recent_turns(10)
    user_contents = [m["content"] for m in out if m["role"] == "user"]
    assert user_contents == ["sql_q"]


def test_lazy_import_handles_corrupt_lines(tmp_path):
    """Malformed JSONL lines are skipped, valid ones still come
    through — a single bad line doesn't drop the rest."""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()
    with (mem_dir / "episodic.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"user": "ok1", "decision_raw": "a1",
                              "session_key": "default"}) + "\n")
        fh.write("{ this is not json\n")
        fh.write(json.dumps({"user": "ok2", "decision_raw": "a2",
                              "session_key": "default"}) + "\n")

    mem.bind(SimpleNamespace(memory_dir=mem_dir))
    out = mem.load_recent_turns(10)
    user_contents = [m["content"] for m in out if m["role"] == "user"]
    assert user_contents == ["ok1", "ok2"]
