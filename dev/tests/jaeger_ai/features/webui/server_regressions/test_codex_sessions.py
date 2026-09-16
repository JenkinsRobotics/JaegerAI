from __future__ import annotations

import json


def _write_rollout(path):
    rows = [
        {
            "type": "session_meta",
            "timestamp": "2026-09-16T20:00:00Z",
            "payload": {"id": "thread-123", "cwd": "/tmp/project", "model_provider": "openai"},
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-16T20:00:01Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /tmp/project\ncontext"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-16T20:00:02Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<environment_context>ignored</environment_context>"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-16T20:00:03Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Why is this session missing?"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-16T20:00:04Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "It is visible now."}],
            },
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_codex_rollout_is_projected_as_read_only_external_session(tmp_path):
    from api.codex_sessions import get_codex_session_messages, get_codex_sessions

    rollout = tmp_path / "2026/09/16/rollout-thread-123.jsonl"
    _write_rollout(rollout)

    sessions = get_codex_sessions(tmp_path)
    assert len(sessions) == 1
    session = sessions[0]
    assert session["title"] == "Why is this session missing?"
    assert session["source_label"] == "Codex"
    assert session["session_source"] == "external_agent"
    assert session["read_only"] is True
    assert session["profile"] is None

    messages = get_codex_session_messages(session["session_id"], tmp_path)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Why is this session missing?"


def test_codex_session_projection_rejects_oversized_rollout(tmp_path):
    from api.codex_sessions import get_codex_sessions

    rollout = tmp_path / "rollout-too-large.jsonl"
    _write_rollout(rollout)

    assert get_codex_sessions(tmp_path)
    assert get_codex_sessions(tmp_path, max_file_bytes=1) == []


def test_codex_session_is_visible_in_each_profile_sidebar():
    from api.routes import _session_visible_in_profile_sidebar

    row = {
        "session_id": "codex_example",
        "profile": None,
        "source_tag": "codex",
        "raw_source": "codex",
        "session_source": "external_agent",
    }

    assert _session_visible_in_profile_sidebar(row, "default") is True
    assert _session_visible_in_profile_sidebar(row, "jaeger") is True
