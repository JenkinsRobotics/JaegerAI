"""Gateway (OWNER) turns write tool_calls rows and trace.jsonl again.

Both writers lived only on the CLI path; after Gateway turns took over
(2026-09-23) state.db tool_calls and logs/trace.jsonl stopped growing.
"""

from __future__ import annotations

import json
import time

import pytest

from jaeger_ai.core.entity.owner_agent import observe_tool_calls, traced_turn
from jaeger_ai.core.instance.instance import InstanceLayout


@pytest.fixture
def layout(tmp_path):
    lay = InstanceLayout(root=tmp_path / "inst")
    lay.root.mkdir(parents=True)
    lay.ensure_dirs()
    from jaeger_agent.memory import sqlite_store
    sqlite_store.bind(lay)
    yield lay


def test_tool_done_records_a_row_and_still_calls_the_original(layout):
    from jaeger_agent import AgentCallbacks
    from jaeger_agent.memory import memory as mem

    seen = []
    cb = observe_tool_calls(AgentCallbacks(tool_done=lambda *a: seen.append(a[0])), "sess-1")
    cb.on_tool_done("terminal", {"command": "pwd"}, {"ok": True}, True, None, 0.25)
    cb.on_tool_done("write_file", {"path": "x"}, {"error": "nope"}, False, "nope", 0.01)
    assert seen == ["terminal", "write_file"]
    rows = mem.list_tool_calls(session_key="sess-1")
    names = sorted((r["tool_name"], bool(r["ok"])) for r in rows)
    assert names == [("terminal", True), ("write_file", False)]


def test_observing_twice_does_not_double_record(layout):
    from jaeger_agent.memory import memory as mem

    cb = observe_tool_calls(observe_tool_calls(None, "sess-2"), "sess-2")
    cb.on_tool_done("read_file", {}, {}, True, None, 0.0)
    assert len(mem.list_tool_calls(session_key="sess-2")) == 1


def test_traced_turn_appends_input_and_answer_to_trace_jsonl(layout, monkeypatch):
    from jaeger_agent.core import trace as _trace
    monkeypatch.setattr(_trace, "_recorder_started", False)
    path = layout.logs_dir / "trace.jsonl"
    before = path.read_text().count("\n") if path.exists() else 0
    with traced_turn(layout, "sess-3", "hello") as t:
        t.answer = "hi"
    deadline = time.time() + 5
    rows = []
    while time.time() < deadline:
        if path.exists():
            rows = [json.loads(l) for l in path.read_text().splitlines()[before:]]
            if any(r["kind"] == "answer" for r in rows):
                break
        time.sleep(0.05)
    kinds = [r["kind"] for r in rows]
    assert "input" in kinds and "answer" in kinds
    assert all("hello" not in json.dumps(r) for r in rows)  # content never persisted
