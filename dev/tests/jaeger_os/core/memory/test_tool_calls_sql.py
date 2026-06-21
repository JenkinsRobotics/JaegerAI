"""DB-6 — tool_calls table SQL backend.

Pin the contract of ``record_tool_call`` + ``list_tool_calls`` against
the schema in ``sqlite_store``: every dispatch lands as one row, with
redacted args/result + ok/error + timing. The agent-loop wiring
fires this from a ``tool_done`` callback after every dispatch.
"""

from __future__ import annotations

import json
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


# ── record_tool_call: basic shape ─────────────────────────────────


def test_record_tool_call_returns_row_id(bound):
    rid = mem.record_tool_call(
        session_key="default",
        tool_name="get_time",
        args={"tz": "UTC"},
        result={"ok": True, "iso": "2026-05-26T00:00:00+00:00"},
        ok=True,
        elapsed_s=0.012,
    )
    assert isinstance(rid, int)
    assert rid >= 1


def test_record_tool_call_returns_none_when_unbound():
    """Before bind, record_tool_call no-ops. Important for tests
    that import memory without binding (and for the daemon's
    pre-bind boot path)."""
    sqlite_store.close()
    out = mem.record_tool_call(
        session_key="x", tool_name="t", args={}, result=None,
    )
    assert out is None


def test_record_persists_all_columns(bound):
    mem.record_tool_call(
        session_key="tui",
        tool_name="run_shell",
        args={"cmd": "ls"},
        result={"stdout": "a\nb\n", "exit_code": 0},
        ok=True,
        elapsed_s=0.5,
    )
    conn = sqlite_store.connection()
    row = conn.execute(
        "SELECT session_key, tool_name, args_json, result_json,"
        " ok, error, elapsed_s, ts FROM tool_calls"
    ).fetchone()
    assert row["session_key"] == "tui"
    assert row["tool_name"] == "run_shell"
    assert json.loads(row["args_json"]) == {"cmd": "ls"}
    assert json.loads(row["result_json"]) == {
        "stdout": "a\nb\n", "exit_code": 0,
    }
    assert row["ok"] == 1
    assert row["error"] is None
    assert row["elapsed_s"] == 0.5
    assert row["ts"]


def test_record_failure_row(bound):
    mem.record_tool_call(
        session_key="default",
        tool_name="broken_tool",
        args={"x": 1},
        result={"ok": False, "error": "boom"},
        ok=False,
        error="boom",
        elapsed_s=0.001,
    )
    conn = sqlite_store.connection()
    row = conn.execute(
        "SELECT ok, error FROM tool_calls"
    ).fetchone()
    assert row["ok"] == 0
    assert row["error"] == "boom"


def test_record_missing_args_defaults_to_empty(bound):
    """``args=None`` → empty-object JSON, not a NULL. Lets training
    extractors query ``json_extract(args_json, '$.x')`` without
    NULL guards everywhere."""
    mem.record_tool_call(
        session_key="default", tool_name="zero_arg", args=None,
        result={"ok": True},
    )
    conn = sqlite_store.connection()
    row = conn.execute("SELECT args_json FROM tool_calls").fetchone()
    assert json.loads(row["args_json"]) == {}


def test_record_missing_result_persists_null(bound):
    """``result=None`` → SQL NULL. Tells the query layer "no result
    captured" vs "result was a JSON null/empty object"."""
    mem.record_tool_call(
        session_key="default", tool_name="no_result", args={"x": 1},
        result=None,
    )
    conn = sqlite_store.connection()
    row = conn.execute("SELECT result_json FROM tool_calls").fetchone()
    assert row["result_json"] is None


def test_record_handles_non_serialisable_args(bound):
    """Args containing non-JSON-able values fall back to ``str``
    via ``default=str`` — must not crash the call."""
    class _Weird:
        def __repr__(self):
            return "<weird>"

    rid = mem.record_tool_call(
        session_key="default", tool_name="t",
        args={"obj": _Weird()},
        result={"ok": True},
    )
    assert rid is not None
    conn = sqlite_store.connection()
    row = conn.execute("SELECT args_json FROM tool_calls").fetchone()
    decoded = json.loads(row["args_json"])
    assert "weird" in str(decoded["obj"]).lower()


def test_record_handles_non_serialisable_result(bound):
    """Symmetric to the args case."""
    class _Weird:
        def __repr__(self):
            return "<weird-result>"

    rid = mem.record_tool_call(
        session_key="default", tool_name="t",
        args={"x": 1},
        result={"thing": _Weird()},
    )
    assert rid is not None


def test_record_redacts_secret_args(bound):
    """Args with secret-looking keys go through redact_obj before
    landing in the DB. Pin this — we never want raw tokens to
    survive into the training-data extractor."""
    mem.record_tool_call(
        session_key="default",
        tool_name="post",
        args={"url": "https://x", "api_key": "sk-supersecret-12345"},
        result={"ok": True},
    )
    conn = sqlite_store.connection()
    row = conn.execute("SELECT args_json FROM tool_calls").fetchone()
    # Either the value is redacted to a sentinel, or the key is
    # removed entirely — the redactor's choice. What matters is the
    # raw secret string is gone.
    assert "sk-supersecret-12345" not in row["args_json"]


def test_record_explicit_ts_is_honoured(bound):
    mem.record_tool_call(
        session_key="default", tool_name="t",
        args={}, result={"ok": True},
        ts="2020-01-01T00:00:00+00:00",
    )
    conn = sqlite_store.connection()
    row = conn.execute("SELECT ts FROM tool_calls").fetchone()
    assert row["ts"] == "2020-01-01T00:00:00+00:00"


def test_record_links_episodic_id(bound):
    """The episodic_id column ties a tool call back to the turn that
    triggered it — used by training extractors to assemble
    (prompt, tool-trace, answer) triples. FK enforced: must
    reference a real episodic row."""
    mem.append_episodic({"user": "q", "decision_raw": "a",
                         "session_key": "default"})
    conn = sqlite_store.connection()
    ep_id = conn.execute("SELECT id FROM episodic").fetchone()["id"]

    rid = mem.record_tool_call(
        session_key="default", tool_name="t",
        args={}, result={"ok": True},
        episodic_id=ep_id,
    )
    assert rid is not None
    row = conn.execute("SELECT episodic_id FROM tool_calls").fetchone()
    assert row["episodic_id"] == ep_id


def test_record_with_unknown_episodic_id_returns_none(bound):
    """Best-effort posture: an invalid FK is swallowed and the
    function returns None rather than raising. Pin this so the
    agent loop never crashes a turn over a stray episodic_id."""
    rid = mem.record_tool_call(
        session_key="default", tool_name="t",
        args={}, result={"ok": True},
        episodic_id=99999,
    )
    assert rid is None


# ── list_tool_calls ──────────────────────────────────────────────


def test_list_returns_newest_first(bound):
    for i in range(3):
        mem.record_tool_call(
            session_key="default", tool_name=f"t{i}",
            args={"i": i}, result={"ok": True},
        )
    rows = mem.list_tool_calls()
    assert [r["tool_name"] for r in rows] == ["t2", "t1", "t0"]


def test_list_filters_by_session_key(bound):
    mem.record_tool_call(session_key="tui", tool_name="a", args={}, result={"ok": True})
    mem.record_tool_call(session_key="work", tool_name="b", args={}, result={"ok": True})
    mem.record_tool_call(session_key="tui", tool_name="c", args={}, result={"ok": True})

    tui_rows = mem.list_tool_calls(session_key="tui")
    assert {r["tool_name"] for r in tui_rows} == {"a", "c"}


def test_list_filters_by_tool_name(bound):
    mem.record_tool_call(session_key="default", tool_name="shell", args={}, result={"ok": True})
    mem.record_tool_call(session_key="default", tool_name="search", args={}, result={"ok": True})
    mem.record_tool_call(session_key="default", tool_name="shell", args={}, result={"ok": True})

    rows = mem.list_tool_calls(tool_name="shell")
    assert len(rows) == 2
    assert all(r["tool_name"] == "shell" for r in rows)


def test_list_respects_limit(bound):
    for i in range(10):
        mem.record_tool_call(
            session_key="default", tool_name="t",
            args={"i": i}, result={"ok": True},
        )
    assert len(mem.list_tool_calls(limit=3)) == 3


def test_list_decodes_args_and_result_json(bound):
    mem.record_tool_call(
        session_key="default", tool_name="t",
        args={"a": 1, "b": [2, 3]},
        result={"ok": True, "value": "hi"},
    )
    rows = mem.list_tool_calls()
    assert rows[0]["args"] == {"a": 1, "b": [2, 3]}
    assert rows[0]["result"] == {"ok": True, "value": "hi"}


def test_list_returns_empty_when_no_rows(bound):
    assert mem.list_tool_calls() == []


# ── _safe_loads helper ───────────────────────────────────────────


def test_safe_loads_handles_none():
    assert mem._safe_loads(None) is None


def test_safe_loads_handles_valid_json():
    assert mem._safe_loads('{"x": 1}') == {"x": 1}


def test_safe_loads_handles_corrupt_json_string():
    """Falls back to raw string on parse failure — never crashes the
    list query."""
    assert mem._safe_loads("not valid json") == "not valid json"


# ── agent-loop wiring (via tool_done callback) ───────────────────


def test_agent_tool_done_callback_records_to_sql(bound):
    """End-to-end-ish: build a JaegerAgent with the tool_done callback
    wired the way main.py wires it, fire a fake dispatch, and assert
    the row landed. Doesn't need a real model — just the dispatch
    plumbing in _dispatch_one_tool."""
    from jaeger_os.agent.loop.callbacks import AgentCallbacks

    captured = []

    def _tool_done(name, args, result, ok, error, elapsed_s):
        # Same shape as main.py's wiring
        rid = mem.record_tool_call(
            session_key="testkey",
            tool_name=name,
            args=args,
            result=result,
            ok=ok,
            error=error,
            elapsed_s=elapsed_s,
        )
        captured.append(rid)

    cb = AgentCallbacks(tool_done=_tool_done)
    # Invoke the safe-invocation helper directly — same surface the
    # agent loop uses.
    cb.on_tool_done(
        "my_tool", {"x": 1}, {"ok": True, "value": "hi"},
        True, None, 0.05,
    )
    assert captured == [1]
    rows = mem.list_tool_calls()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "my_tool"
    assert rows[0]["args"] == {"x": 1}
    assert rows[0]["ok"] is True
    assert rows[0]["session_key"] == "testkey"


def test_agent_tool_done_callback_swallows_handler_errors(bound):
    """The on_tool_done helper must swallow exceptions from the
    handler — same posture as every other callback. A buggy
    observer cannot break a turn."""
    from jaeger_os.agent.loop.callbacks import AgentCallbacks

    def _broken(name, args, result, ok, error, elapsed_s):
        raise RuntimeError("boom")

    cb = AgentCallbacks(tool_done=_broken)
    # No assertion — just must not raise.
    cb.on_tool_done("t", {}, {"ok": True}, True, None, 0.0)


def test_agent_tool_done_callback_noop_when_unset(bound):
    """Default AgentCallbacks (no tool_done) is a silent no-op."""
    from jaeger_os.agent.loop.callbacks import AgentCallbacks

    cb = AgentCallbacks()  # all callbacks None
    cb.on_tool_done("t", {}, {"ok": True}, True, None, 0.0)
    # No row written, no crash.
    assert mem.list_tool_calls() == []
