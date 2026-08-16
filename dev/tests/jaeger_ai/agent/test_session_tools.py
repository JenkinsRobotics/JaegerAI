"""Unit tests for Jaeger AI session_search and browsing tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jaeger_ai.core.session_tools import (
    _classify_source,
    _format_ts,
    session_search,
)


@pytest.fixture
def mock_ares_session_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary ARES session directory with sample sessions."""
    sdir = tmp_path / "sessions"
    sdir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARES_SESSION_DIR", str(sdir))
    monkeypatch.setenv("ARES_CONTROLLER_PORT", "99999")  # Unreachable port to force disk index

    # Create _index.json with WebUI and CLI sessions
    index_data = [
        {
            "session_id": "web_sess_1",
            "title": "Discussing neural architectures",
            "created_at": 1786800000.0,
            "updated_at": 1786800100.0,
            "message_count": 4,
            "source_tag": "webui",
            "is_cli_session": False,
        },
        {
            "session_id": "web_sess_2",
            "title": "Debugging Swift client tests",
            "created_at": 1786800200.0,
            "updated_at": 1786800300.0,
            "message_count": 6,
            "source_tag": "webui",
            "is_cli_session": False,
        },
        {
            "session_id": "cli_sess_1",
            "title": "Claude code session on backend router",
            "created_at": 1786800400.0,
            "updated_at": 1786800500.0,
            "message_count": 12,
            "source_tag": "claude_code",
            "is_cli_session": True,
            "source_label": "Claude Code",
        },
    ]

    (sdir / "_index.json").write_text(json.dumps(index_data), encoding="utf-8")

    # Create detailed transcript for web_sess_1
    (sdir / "web_sess_1.json").write_text(
        json.dumps({
            "session_id": "web_sess_1",
            "title": "Discussing neural architectures",
            "created_at": 1786800000.0,
            "model": "qwen3.5:397b",
            "context_messages": [
                {"role": "user", "content": "How do transformer attention heads work?", "timestamp": 1786800010.0},
                {"role": "assistant", "content": "Attention heads project inputs into query, key, value spaces.", "timestamp": 1786800020.0},
            ],
        }),
        encoding="utf-8",
    )

    return sdir


def test_classify_source():
    assert _classify_source({"source_tag": "webui", "is_cli_session": False}) == "webui"
    assert _classify_source({"source_tag": "claude_code", "is_cli_session": True}) == "cli"
    assert _classify_source({"is_cli_session": True}) == "cli"
    assert _classify_source({"raw_source": "tui"}) == "cli"
    assert _classify_source({"raw_source": "acp"}) == "cli"
    assert _classify_source({}) == "webui"


def test_format_ts():
    assert _format_ts(None) == "unknown"
    formatted = _format_ts(1786800000.0)
    assert len(formatted) > 5


def test_session_search_browse_mode(mock_ares_session_tree: Path):
    result = session_search()
    assert result["ok"] is True
    assert result["mode"] == "browse"
    assert result["total_sessions"] == 3
    assert result["webui_sessions_count"] == 2
    assert result["cli_sessions_count"] == 1
    assert "2 WebUI sessions, 1 CLI sessions" in result["summary"]
    assert len(result["sessions"]) == 3


def test_session_search_filter_by_source(mock_ares_session_tree: Path):
    webui_res = session_search(source="webui")
    assert webui_res["ok"] is True
    assert len(webui_res["sessions"]) == 2
    assert all(s["source"] == "webui" for s in webui_res["sessions"])

    cli_res = session_search(source="cli")
    assert cli_res["ok"] is True
    assert len(cli_res["sessions"]) == 1
    assert cli_res["sessions"][0]["session_id"] == "cli_sess_1"


def test_session_search_query_mode(mock_ares_session_tree: Path):
    # Search by title keyword
    res = session_search(query="architectures")
    assert res["ok"] is True
    assert res["mode"] == "search"
    assert res["total_matches"] == 1
    assert res["sessions"][0]["session_id"] == "web_sess_1"

    # Search by transcript content keyword
    res2 = session_search(query="attention heads")
    assert res2["ok"] is True
    assert res2["total_matches"] == 1
    assert res2["sessions"][0]["session_id"] == "web_sess_1"
    assert "matched_snippet" in res2["sessions"][0]


def test_session_search_read_mode(mock_ares_session_tree: Path):
    res = session_search(session_id="web_sess_1")
    assert res["ok"] is True
    assert res["mode"] == "read"
    session_data = res["session"]
    assert session_data["session_id"] == "web_sess_1"
    assert session_data["title"] == "Discussing neural architectures"
    assert session_data["message_count"] == 2
    assert len(session_data["messages"]) == 2
    assert session_data["messages"][0]["role"] == "user"
    assert "transformer" in session_data["messages"][0]["content"]


def test_session_search_nonexistent_session(mock_ares_session_tree: Path):
    res = session_search(session_id="non_existent_id")
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_session_search_registered_in_registry():
    from jaeger_ai.main import _register_builtins
    from jaeger_os.core.tools.tool_registry import has_tool
    _register_builtins(None)
    assert has_tool("session_search") is True
