import json

from jaeger_ai.features.history_import.claude import ClaudeHistorySource
from jaeger_ai.features.history_import.codex import CodexHistorySource
from jaeger_ai.features.history_import.gemini import GeminiHistorySource
from jaeger_ai.features.history_import.grok import GrokHistorySource


def _jsonl(path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def test_claude_nested_message_format(tmp_path) -> None:
    path = tmp_path / "project" / "session.jsonl"
    _jsonl(path, [{
        "type": "user",
        "sessionId": "abc",
        "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    }])
    parsed = ClaudeHistorySource(tmp_path).parse(path)
    assert parsed is not None
    assert parsed.original_id == "abc"
    assert parsed.messages[0]["text"] == "hello"


def test_codex_response_item_format(tmp_path) -> None:
    path = tmp_path / "rollout.jsonl"
    _jsonl(path, [
        {"type": "session_meta", "payload": {"id": "abc", "cwd": "/repo"}},
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            },
        },
    ])
    parsed = CodexHistorySource(tmp_path).parse(path)
    assert parsed is not None
    assert parsed.messages[0]["text"] == "done"


def test_gemini_uses_latest_message_snapshot(tmp_path) -> None:
    path = tmp_path / "project" / "chats" / "session.jsonl"
    _jsonl(path, [
        {"$set": {"messages": [{"type": "user", "content": "old"}]}},
        {"$set": {"messages": [{"type": "user", "content": "new"}]}},
    ])
    parsed = GeminiHistorySource(tmp_path).parse(path)
    assert parsed is not None
    assert [row["text"] for row in parsed.messages] == ["new"]


def test_grok_native_session_format(tmp_path) -> None:
    path = tmp_path / "%2Frepo" / "grok-id" / "chat_history.jsonl"
    _jsonl(path, [{"type": "user", "content": [{"type": "text", "text": "fix"}]}])
    parsed = GrokHistorySource(tmp_path).parse(path)
    assert parsed is not None
    assert parsed.workspace == "/repo"
    assert parsed.messages[0]["text"] == "fix"
