"""The agent session tool reads only Jaeger's canonical transcript store."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core import sessions
from jaeger_ai.core.session_tools import _format_ts, session_search


@pytest.fixture
def bound_store(tmp_path, monkeypatch):
    sessions.reset_for_tests()
    layout = SimpleNamespace(memory_dir=tmp_path / "memory")
    monkeypatch.setitem(__import__("jaeger_ai.main", fromlist=["_pipeline"])._pipeline, "layout", layout)
    store = sessions.get_store(layout)
    assert store is not None
    store.record("older", "user", "transformer attention heads")
    store.record("older", "assistant", "queries, keys, and values")
    store.set_title("older", "Neural architecture")
    store.record("newer", "user", "debug the bridge")
    yield store
    sessions.reset_for_tests()


def test_format_ts():
    assert _format_ts(None) == "unknown"
    assert len(_format_ts(1786800000.0)) > 5


def test_session_search_browse_mode(bound_store):
    result = session_search()
    assert result["ok"] is True
    assert result["mode"] == "browse"
    assert result["total_sessions"] == 2
    assert all(row["source"] == "jaeger" for row in result["sessions"])


def test_session_search_query_uses_runtime_store(bound_store):
    result = session_search(query="attention heads")
    assert result["mode"] == "search"
    assert result["total_matches"] == 1
    assert result["sessions"][0]["session_id"] == "older"


def test_session_search_read_returns_tool_metadata(bound_store):
    bound_store.record(
        "newer",
        "assistant",
        "done",
        metadata={"tool_calls": [{"name": "write_file", "done": True}]},
    )
    result = session_search(session_id="newer")
    assert result["ok"] is True
    assert result["session"]["messages"][-1]["metadata"] == {
        "tool_calls": [{"name": "write_file", "done": True}],
    }


def test_session_search_rejects_foreign_source_without_reading_it(bound_store):
    result = session_search(source="webui")
    assert result["sessions"] == []
    assert result["total_sessions"] == 0


def test_session_search_nonexistent_session(bound_store):
    result = session_search(session_id="missing")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_session_search_registered_in_registry():
    from jaeger_ai.main import _register_builtins
    from jaeger_os.core.tools.tool_registry import has_tool

    _register_builtins(None)
    assert has_tool("session_search") is True
