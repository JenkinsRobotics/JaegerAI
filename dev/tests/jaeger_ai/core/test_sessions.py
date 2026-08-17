"""SQLite session persistence — conversations survive app close.

Pin: turns are recorded, history round-trips in order, list_sessions ranks
by recency with preview + count, titles set, and an empty store is clean.
"""

from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from jaeger_ai.core.sessions import SessionStore, canonical_session_id


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


def test_delete_removes_exact_session_and_messages(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("keep", "user", "keep me")
        store.record("drop", "user", "remove me")
        assert store.delete("drop") is True
        assert store.delete("drop") is False
        assert store.history("drop") == []
        assert [row["id"] for row in store.list_sessions()] == ["keep"]
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


def test_session_remembers_the_brain_that_served_it(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "hi")
        store.stamp_brain(
            "s1", model="deepseek-v4-flash:preview", provider="ollama-cloud",
        )
        assert store.brain("s1") == {
            "model": "deepseek-v4-flash:preview",
            "provider": "ollama-cloud",
        }
        assert store.brain("missing") == {"model": None, "provider": None}
    finally:
        store.close()


def test_shared_id_normalizes_only_the_legacy_ares_alias():
    assert canonical_session_id("webui:abc-123") == "abc-123"
    assert canonical_session_id("telegram:42") == "telegram:42"


def test_open_migrates_legacy_webui_rows_to_shared_ids(tmp_path):
    path = tmp_path / "s.db"
    legacy = SessionStore(path)
    legacy.record("shared-1", "user", "legacy turn")
    legacy.close()
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "UPDATE messages SET session_id='webui:shared-1' WHERE session_id='shared-1'"
        )
        conn.execute("UPDATE sessions SET id='webui:shared-1' WHERE id='shared-1'")
    conn.close()

    store = SessionStore(path)
    try:
        assert [row["id"] for row in store.list_sessions()] == ["shared-1"]
        assert store.history("shared-1")[0]["text"] == "legacy turn"
        conn = sqlite3.connect(path)
        try:
            assert conn.execute(
                "SELECT count(*) FROM sessions WHERE id LIKE 'webui:%'"
            ).fetchone()[0] == 0
        finally:
            conn.close()
    finally:
        store.close()


def test_delete_tombstone_is_idempotent_and_blocks_stale_reimport(tmp_path):
    path = tmp_path / "s.db"
    store = SessionStore(path)
    try:
        assert store.create("shared-1") == {
            "id": "shared-1", "created": True, "tombstoned": False,
        }
        assert store.create("shared-1")["created"] is False
        store.record("shared-1", "user", "remove me")
        assert store.delete("shared-1") is True
        assert store.delete("shared-1") is False
        assert store.is_tombstoned("shared-1") is True
        assert store.create("shared-1")["tombstoned"] is True
        store.record("shared-1", "user", "stale replay")
        assert store.history("shared-1") == []
    finally:
        store.close()
    restarted = SessionStore(path)
    try:
        assert restarted.is_tombstoned("shared-1") is True
        restarted.record("shared-1", "user", "restart replay")
        assert restarted.history("shared-1") == []
    finally:
        restarted.close()


def test_clear_search_and_tool_metadata_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("shared-1", "user", "find this needle")
        store.record(
            "shared-1", "assistant", "done",
            metadata={"tool_calls": [{"name": "write_file", "done": True}]},
        )
        assert [row["id"] for row in store.search("needle")] == ["shared-1"]
        assert store.history("shared-1")[-1]["metadata"]["tool_calls"][0]["name"] == "write_file"
        assert store.clear("shared-1") is True
        assert store.clear("missing") is False
        assert store.history("shared-1") == []
        assert store.exists("shared-1") is True
    finally:
        store.close()


def test_reconcile_visible_transcript_only_rewrites_matching_user_rows(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("shared-1", "user", "[directive] visible")
        store.record("shared-1", "assistant", "same answer")
        result = store.reconcile_visible_transcript("shared-1", [
            {"role": "user", "text": "visible"},
            {"role": "assistant", "text": "same answer"},
        ])
        assert result["updated_user_messages"] == 1
        assert store.history("shared-1")[0]["text"] == "visible"
        with pytest.raises(ValueError, match="assistant transcript"):
            store.reconcile_visible_transcript("shared-1", [
                {"role": "user", "text": "visible"},
                {"role": "assistant", "text": "different answer"},
            ])
    finally:
        store.close()


def test_running_execution_state_becomes_interrupted_after_restart(tmp_path):
    path = tmp_path / "s.db"
    store = SessionStore(path)
    store.create("shared-1")
    assert store.set_execution_state("shared-1", "running") is True
    assert store.list_sessions()[0]["execution_state"] == "running"
    store.close()

    restarted = SessionStore(path)
    try:
        assert restarted.list_sessions()[0]["execution_state"] == "interrupted"
    finally:
        restarted.close()


def test_concurrent_delete_tombstone_prevents_late_turn_resurrection(tmp_path):
    """A racing turn may finish after delete, but it cannot recreate history."""
    store = SessionStore(tmp_path / "s.db")
    store.record("shared-1", "user", "before delete")
    deleted = threading.Event()

    def late_turn() -> None:
        deleted.wait(timeout=2)
        store.record("shared-1", "assistant", "late result")

    worker = threading.Thread(target=late_turn)
    worker.start()
    try:
        assert store.delete("shared-1") is True
        deleted.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert store.is_tombstoned("shared-1") is True
        assert store.history("shared-1") == []
        assert store.exists("shared-1") is False
    finally:
        deleted.set()
        worker.join(timeout=2)
        store.close()


def test_session_messages_and_tool_metadata_never_persist_secrets(tmp_path):
    path = tmp_path / "s.db"
    secret = "ghp_TestFakeCredential1234567890ab"
    store = SessionStore(path)
    store.record(
        "shared-1",
        "user",
        f"token={secret}",
        metadata={"tool_calls": [{"args": {"api_key": secret}}]},
    )
    history = store.history("shared-1")
    assert secret not in json.dumps(history)
    assert "[REDACTED]" in history[0]["text"]
    store.close()

    # Migration also scrubs rows written by an older version.
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(
            "UPDATE messages SET text=?, metadata=? WHERE session_id=?",
            (secret, json.dumps({"password": secret}), "shared-1"),
        )
        conn.execute(
            "UPDATE sessions SET preview=? WHERE id=?", (secret, "shared-1")
        )
    conn.close()
    restarted = SessionStore(path)
    try:
        assert secret not in json.dumps(restarted.history("shared-1"))
        assert secret not in json.dumps(restarted.list_sessions())
    finally:
        restarted.close()


def test_session_messages_mask_opaque_secret_metadata_values(tmp_path):
    store = SessionStore(tmp_path / "sessions.db")
    store.record(
        "secret-metadata",
        "assistant",
        "configured",
        metadata={"api_key": "opaque-value", "nested": {"password": "plain-word"}},
    )

    metadata = store.history("secret-metadata")[0]["metadata"]
    assert metadata["api_key"] == "[REDACTED]"
    assert metadata["nested"]["password"] == "[REDACTED]"
    store.close()
