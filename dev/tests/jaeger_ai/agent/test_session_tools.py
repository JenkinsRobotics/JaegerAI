"""The agent session tool reads only the authoritative Gateway API."""

import pytest

import jaeger_ai.core.session_tools as session_tools
from jaeger_ai.core.session_tools import _format_ts, session_search


class _Gateway:
    rows = [
        {"session_id": "newer", "title": "Bridge", "message_count": 1, "status": "idle"},
        {"session_id": "older", "title": "Neural architecture", "message_count": 2, "status": "idle"},
    ]

    def list_sessions(self):
        return list(self.rows)

    def get_session(self, session_id):
        rows = [row for row in self.rows if row["session_id"] == session_id]
        return ({**rows[0], "messages": [
            {"role": "assistant", "content": "done", "metadata": {"tool_calls": []}},
        ]} if rows else None)

    def _call(self, method, path):
        assert method == "GET"
        return {"sessions": [self.rows[1]] if "attention%20heads" in path else []}


@pytest.fixture(autouse=True)
def gateway(monkeypatch):
    monkeypatch.setattr(session_tools, "_gateway", lambda: _Gateway())


def test_format_ts():
    assert len(_format_ts(1786800000.0)) > 5


def test_session_search_browse_reports_total_independent_of_limit():
    result = session_search(limit=1)
    assert result["total_sessions"] == 2
    assert len(result["sessions"]) == 1


def test_session_search_query_uses_gateway_search():
    result = session_search(query="attention heads")
    assert result["total_matches"] == 1
    assert result["sessions"][0]["session_id"] == "older"


def test_session_search_read_uses_gateway_transcript():
    result = session_search(session_id="newer")
    assert result["ok"] is True
    assert result["session"]["messages"][-1]["content"] == "done"


def test_session_search_registered_in_registry():
    from jaeger_ai.main import _register_builtins
    from jaeger_os.core.tools.tool_registry import has_tool
    _register_builtins(None)
    assert has_tool("session_search") is True
