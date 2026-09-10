"""KEEP/ARCHIVE classification, vendor import, and ended_at close-out."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from jaeger_ai.core.sessions import SessionStore
from jaeger_ai.features.hermes_webui.session_unify import (
    ROLLBACK_MIN_KEEP,
    infer_session_profile,
    profile_badge_for_session,
    backfill_jaeger_titles,
    freeze_sources,
    import_keep,
    is_junk,
    is_system_nudge,
    reconcile_keep,
    stamp_ended_at,
    title_from_text,
)
from jaeger_ai.interfaces.hermes_profile_adapters.native_runs import Runs, TERMINAL


def _hermes_db(path: Path, rows: list[tuple]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, title TEXT, "
        "message_count INTEGER, ended_at REAL)"
    )
    conn.execute(
        "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, "
        "content TEXT, timestamp REAL)"
    )
    conn.executemany(
        "INSERT INTO sessions(id, source, title, message_count) VALUES (?,?,?,?)",
        rows,
    )
    for sid, _source, title, count in rows:
        for i in range(int(count or 0)):
            conn.execute(
                "INSERT INTO messages(session_id, role, content, timestamp) VALUES (?,?,?,?)",
                (sid, "user" if i == 0 else "assistant", title or sid, float(i)),
            )
    conn.commit()
    conn.close()


def test_junk_classification_keeps_roundtable_and_dispatcher() -> None:
    assert is_junk(session_id="dispatcher", messages=2)[0] is False
    assert is_junk(session_id="roundtable-hermes:abc", messages=5)[0] is False
    assert is_junk(session_id="x", preview="Hold the check word ROUNDTABLE", messages=2)[0] is True
    assert is_junk(session_id="empty", messages=0)[0] is True


def test_reconcile_keep_unions_state_db_and_json(tmp_path: Path) -> None:
    state = tmp_path / "state.db"
    _hermes_db(state, [
        ("roundtable-hermes:keepme", "webui", "Roundtable work", 6),
        ("probe-1", "webui", "Hold the check word X", 2),
        ("real-chat", "webui", "Why is the webui not correct", 4),
    ])
    webui = tmp_path / "webui"
    webui.mkdir()
    (webui / "json-only.json").write_text(
        json.dumps({"session_id": "json-only", "title": "Mac app chat", "message_count": 3}),
        encoding="utf-8",
    )
    (webui / "_index.json").write_text(
        json.dumps([{"session_id": "json-only", "title": "Mac app chat", "message_count": 3}]),
        encoding="utf-8",
    )
    result = reconcile_keep(hermes_state_db=state, webui_sessions=webui)
    keep_ids = {row["id"] for row in result["keep"]}
    assert "roundtable-hermes:keepme" in keep_ids
    assert "real-chat" in keep_ids
    assert "json-only" in keep_ids
    assert "probe-1" not in keep_ids
    assert result["state_only"] >= 1
    assert result["rollback"] is False or len(result["keep"]) < ROLLBACK_MIN_KEEP


def test_import_keep_copies_roundtable_into_vendor_state_db(tmp_path: Path) -> None:
    src = tmp_path / "hermes-state.db"
    _hermes_db(src, [
        ("roundtable-hermes:keepme", "webui", "Roundtable work", 6),
        ("probe-1", "webui", "Hold the check word X", 2),
        ("real-chat", "webui", "Why is the webui not correct", 4),
        ("dispatcher", "webui", "Dispatcher", 2),
        ("76c4ddbe5faa", "webui", "Audit sessions", 9),
        ("960f4565", "webui", "Make you usable", 8),
        ("b8349b0769d3", "webui", "Wrong port", 4),
        ("b392eea6", "webui", "Prime directive", 4),
    ])
    webui = tmp_path / "webui"
    webui.mkdir()
    agent = tmp_path / "vendor-agent"
    state_dir = tmp_path / "vendor-state"
    keep_ids = [
        "roundtable-hermes:keepme", "real-chat", "dispatcher",
        "76c4ddbe5faa", "960f4565", "b8349b0769d3", "b392eea6",
    ]
    result = import_keep(
        hermes_state_db=src,
        webui_sessions=webui,
        vendor_agent_home=agent,
        vendor_webui_state=state_dir,
        keep_ids=keep_ids,
    )
    assert result["sessions"] >= 6
    assert result["rollback"] is False
    dest = sqlite3.connect(str(agent / "state.db"))
    cols = {row[1] for row in dest.execute("PRAGMA table_info(sessions)")}
    assert "source" in cols
    ids = {row[0] for row in dest.execute("SELECT id FROM sessions")}
    assert "roundtable-hermes:keepme" in ids
    assert "probe-1" not in ids
    n = dest.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert n >= 6
    dest.close()


def test_stamp_ended_at_closes_session(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    _hermes_db(db, [("roundtable-hermes:x", "webui", "t", 2)])
    assert stamp_ended_at(db, "roundtable-hermes:x") is True
    ended = sqlite3.connect(str(db)).execute(
        "SELECT ended_at FROM sessions WHERE id=?", ("roundtable-hermes:x",)
    ).fetchone()[0]
    assert ended is not None


def test_reconcile_stamps_ended_at_without_replay(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "vendor" / "state.db"
    db.parent.mkdir()
    _hermes_db(db, [("web-session", "webui", "t", 2)])
    monkeypatch.setattr(
        "jaeger_ai.features.hermes_webui.session_unify.close_reconciled_webui_session",
        lambda sid: stamp_ended_at(db, sid),
    )
    def backend(run, workspace):
        run.dispatch(session_id="native", run_id=run.id)
        return "done"
    def reconciler(native):
        return {**native, "execution_unknown": False, "status": "failed", "output": ""}
    runs = Runs(tmp_path / "runs", backend, reconciler=reconciler)
    info = runs.start("web-session", "hello")
    run = runs.get(info["run_id"])
    deadline = time.monotonic() + 3
    while run.worker_active and time.monotonic() < deadline:
        time.sleep(0.01)
    run.status = "interrupted"
    run.execution_unknown = True
    run.worker_active = False
    run.persist()
    saved = runs.reconcile(info["run_id"])
    assert saved["execution_unknown"] is False
    assert saved["status"] in TERMINAL
    ended = sqlite3.connect(str(db)).execute(
        "SELECT ended_at FROM sessions WHERE id=?", ("web-session",)
    ).fetchone()[0]
    assert ended is not None


def test_nudge_is_not_recorded_as_user(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "hello there")
        store.record("s1", "user", "SYSTEM NUDGE: Do not narrate future actions and do not stop.")
        hist = store.history("s1")
        assert [m["text"] for m in hist] == ["hello there"]
        assert store.list_sessions()[0]["title"] == "hello there"
    finally:
        store.close()


def test_backfill_titles_from_preview(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "s.db")
    try:
        store.record("s1", "user", "Why is the webui not correct")
        store._conn.execute("UPDATE sessions SET title=NULL WHERE id='s1'")
        store._conn.commit()
        assert backfill_jaeger_titles(store) == 1
        assert store.list_sessions()[0]["title"].startswith("Why is the webui")
    finally:
        store.close()


def test_freeze_copies_state_db_and_wal(tmp_path: Path) -> None:
    src = tmp_path / "state.db"
    src.write_bytes(b"sqlite")
    (tmp_path / "state.db-wal").write_bytes(b"wal")
    dest = tmp_path / "backup"
    result = freeze_sources(dest, [src])
    assert (dest / "state.db").exists()
    assert (dest / "state.db-wal").exists()
    assert src.exists()
    assert str(src) in result["copied"]


def test_is_system_nudge_and_title() -> None:
    assert is_system_nudge("SYSTEM NUDGE: keep going")
    assert title_from_text("SYSTEM NUDGE: x\nReal question") == "Real question"


def test_profile_badge_one_library_labels() -> None:
    assert profile_badge_for_session("dispatcher") == "Jaeger"
    assert profile_badge_for_session("x", profile="default") == "Hermes Agent"
    assert profile_badge_for_session("x", profile="hermes") == "Hermes Agent"
    assert profile_badge_for_session("roundtable-hermes:abc") == "Roundtable"
    assert profile_badge_for_session("x", profile="openclaw") == "OpenClaw"
    assert infer_session_profile("web-only", origin="webui") == "jaeger"
