"""DB-7 — audit_log table SQL backend.

Pin the contract of ``record_audit_event`` / ``list_audit_events`` and
the dual-write behaviour of ``core/tools/_common.py:_audit`` (JSONL
stays canonical; SQL is a queryable mirror). Lazy-import from
``logs/audit.log`` covers the upgrade path from pre-0.2.0 instances.
"""

from __future__ import annotations

import json
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
    """Bind memory at a fresh tmp instance with a real audit_log_path."""
    layout = SimpleNamespace(
        memory_dir=tmp_path / "memory",
        logs_dir=tmp_path / "logs",
        audit_log_path=tmp_path / "logs" / "audit.log",
    )
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    mem.bind(layout)
    yield layout


# ── record_audit_event ────────────────────────────────────────────


def test_record_audit_event_returns_row_id(bound):
    rid = mem.record_audit_event(
        event="file_write",
        payload={"path": "skills/foo.py", "bytes": 42},
    )
    assert isinstance(rid, int) and rid >= 1


def test_record_audit_event_returns_none_when_unbound():
    sqlite_store.close()
    out = mem.record_audit_event(event="t", payload={})
    assert out is None


def test_record_persists_all_columns(bound):
    mem.record_audit_event(
        event="run_shell",
        payload={"command": "ls", "timeout_s": 5},
        session_key="tui",
    )
    conn = sqlite_store.connection()
    row = conn.execute(
        "SELECT ts, event, payload_json, session_key FROM audit_log"
    ).fetchone()
    assert row["event"] == "run_shell"
    assert row["session_key"] == "tui"
    decoded = json.loads(row["payload_json"])
    assert decoded == {"command": "ls", "timeout_s": 5}
    assert row["ts"]


def test_record_audit_event_handles_none_payload(bound):
    mem.record_audit_event(event="boot", payload=None)
    conn = sqlite_store.connection()
    row = conn.execute("SELECT payload_json FROM audit_log").fetchone()
    assert json.loads(row["payload_json"]) == {}


def test_record_audit_event_handles_non_serialisable_payload(bound):
    class _Weird:
        def __repr__(self):
            return "<weird>"

    rid = mem.record_audit_event(
        event="t", payload={"thing": _Weird()},
    )
    assert rid is not None
    conn = sqlite_store.connection()
    row = conn.execute("SELECT payload_json FROM audit_log").fetchone()
    decoded = json.loads(row["payload_json"])
    assert "weird" in str(decoded["thing"]).lower()


def test_record_audit_event_explicit_ts(bound):
    mem.record_audit_event(
        event="t", payload={}, ts="2020-01-01T00:00:00+00:00",
    )
    conn = sqlite_store.connection()
    row = conn.execute("SELECT ts FROM audit_log").fetchone()
    assert row["ts"] == "2020-01-01T00:00:00+00:00"


# ── list_audit_events ────────────────────────────────────────────


def test_list_returns_newest_first(bound):
    for i in range(3):
        mem.record_audit_event(event=f"e{i}", payload={"i": i})
    rows = mem.list_audit_events()
    assert [r["event"] for r in rows] == ["e2", "e1", "e0"]


def test_list_filters_by_event(bound):
    mem.record_audit_event(event="file_write", payload={"x": 1})
    mem.record_audit_event(event="run_shell", payload={"x": 2})
    mem.record_audit_event(event="file_write", payload={"x": 3})

    rows = mem.list_audit_events(event="file_write")
    assert len(rows) == 2
    assert all(r["event"] == "file_write" for r in rows)


def test_list_filters_by_session_key(bound):
    mem.record_audit_event(event="t", payload={}, session_key="tui")
    mem.record_audit_event(event="t", payload={}, session_key="voice")
    mem.record_audit_event(event="t", payload={}, session_key="tui")
    rows = mem.list_audit_events(session_key="tui")
    assert len(rows) == 2


def test_list_respects_limit(bound):
    for i in range(10):
        mem.record_audit_event(event="t", payload={"i": i})
    assert len(mem.list_audit_events(limit=3)) == 3


def test_list_decodes_payload_json(bound):
    mem.record_audit_event(
        event="t", payload={"a": 1, "nested": {"b": 2}},
    )
    rows = mem.list_audit_events()
    assert rows[0]["payload"] == {"a": 1, "nested": {"b": 2}}


def test_list_returns_empty_when_no_rows(bound):
    assert mem.list_audit_events() == []


# ── dual-write from _audit() ─────────────────────────────────────


def test_audit_dual_writes_jsonl_and_sql(bound, monkeypatch, tmp_path):
    """The canonical JSONL is appended; SQL gets a mirror row.
    Important: SQL is advisory — if SQL fails, JSONL still wins."""
    from jaeger_ai.core import context as _common

    # _audit needs ``_require_layout`` to succeed. Plug in a layout
    # that points at our bound memory + matching log path.
    monkeypatch.setattr(_common, "_require_layout", lambda: bound)

    _common._audit("file_write", {"path": "x.py", "bytes": 12})

    # JSONL — canonical
    contents = bound.audit_log_path.read_text(encoding="utf-8").strip()
    entry = json.loads(contents.splitlines()[-1])
    assert entry["event"] == "file_write"
    assert entry["path"] == "x.py"
    assert entry["bytes"] == 12

    # SQL — mirror
    rows = mem.list_audit_events(event="file_write")
    assert len(rows) == 1
    assert rows[0]["payload"]["path"] == "x.py"
    assert rows[0]["payload"]["bytes"] == 12


def test_audit_sql_failure_does_not_break_jsonl(bound, monkeypatch):
    """The SQL writer is wrapped in try/except — if record_audit_event
    raises, the JSONL still gets written. Pin this; the audit log
    is a safety surface."""
    from jaeger_ai.core import context as _common

    monkeypatch.setattr(_common, "_require_layout", lambda: bound)
    monkeypatch.setattr(
        mem, "record_audit_event",
        lambda **_kw: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    # Must NOT raise.
    _common._audit("file_write", {"path": "y.py"})
    contents = bound.audit_log_path.read_text(encoding="utf-8").strip()
    assert "file_write" in contents


def test_audit_dual_write_redacts_secrets(bound, monkeypatch):
    """The single redact pass in _audit happens before BOTH the JSONL
    write and the SQL mirror — secrets must be gone in both."""
    from jaeger_ai.core import context as _common
    monkeypatch.setattr(_common, "_require_layout", lambda: bound)

    _common._audit("run_shell", {
        "command": "curl https://x",
        "api_key": "sk-supersecret-12345",
    })
    jsonl_text = bound.audit_log_path.read_text(encoding="utf-8")
    assert "sk-supersecret-12345" not in jsonl_text

    rows = mem.list_audit_events(event="run_shell")
    sql_text = json.dumps(rows[0])
    assert "sk-supersecret-12345" not in sql_text


# ── lazy import from logs/audit.log ──────────────────────────────


def test_lazy_import_brings_legacy_jsonl_into_sql(tmp_path):
    """First-bind copies an existing audit.log JSONL into SQL."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    audit_path = log_dir / "audit.log"
    with audit_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": "2026-01-01T00:00:00+00:00",
            "event": "file_write",
            "path": "x.py",
        }) + "\n")
        fh.write(json.dumps({
            "ts": "2026-01-01T00:01:00+00:00",
            "event": "run_shell",
            "command": "ls",
            "session_key": "tui",
        }) + "\n")

    layout = SimpleNamespace(
        memory_dir=tmp_path / "memory",
        logs_dir=log_dir,
        audit_log_path=audit_path,
    )
    mem.bind(layout)

    rows = mem.list_audit_events(limit=100)
    assert len(rows) == 2
    events = sorted(r["event"] for r in rows)
    assert events == ["file_write", "run_shell"]
    shell_row = next(r for r in rows if r["event"] == "run_shell")
    assert shell_row["session_key"] == "tui"
    assert shell_row["payload"]["command"] == "ls"


def test_lazy_import_skipped_when_sql_has_rows(tmp_path):
    """Idempotent on re-bind — existing SQL rows take precedence."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    audit_path = log_dir / "audit.log"
    layout = SimpleNamespace(
        memory_dir=tmp_path / "memory",
        logs_dir=log_dir,
        audit_log_path=audit_path,
    )

    mem.bind(layout)
    mem.record_audit_event(event="from_sql", payload={"k": 1})
    sqlite_store.close()

    # Stale JSONL on a second bind shouldn't clobber.
    with audit_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "stale", "ts": "2020"}) + "\n")
    mem.bind(layout)

    rows = mem.list_audit_events()
    assert {r["event"] for r in rows} == {"from_sql"}


def test_lazy_import_handles_corrupt_lines(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True)
    audit_path = log_dir / "audit.log"
    with audit_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "ok1", "ts": "2026"}) + "\n")
        fh.write("{ not valid json\n")
        fh.write(json.dumps({"event": "ok2", "ts": "2026"}) + "\n")

    layout = SimpleNamespace(
        memory_dir=tmp_path / "memory",
        logs_dir=log_dir,
        audit_log_path=audit_path,
    )
    mem.bind(layout)
    events = {r["event"] for r in mem.list_audit_events()}
    assert events == {"ok1", "ok2"}


def test_lazy_import_handles_missing_audit_log(tmp_path):
    """No legacy file = no-op, no crash."""
    layout = SimpleNamespace(
        memory_dir=tmp_path / "memory",
        logs_dir=tmp_path / "logs",
        audit_log_path=tmp_path / "logs" / "audit.log",  # doesn't exist
    )
    (tmp_path / "logs").mkdir()
    mem.bind(layout)
    assert mem.list_audit_events() == []
