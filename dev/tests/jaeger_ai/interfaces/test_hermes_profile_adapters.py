from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
import json

from jaeger_ai.core.frameworks import jaeger












def test_jaeger_chat_returns_json_when_body_is_invalid():
    handler = object.__new__(jaeger.RunHandler)
    handler.headers = {"Content-Length": "3"}
    handler.rfile = BytesIO(b"{no")
    captured = {}
    handler._send_json = lambda status, payload: captured.update(status=status, payload=payload)

    handler._handle_chat_completions()

    assert captured["status"] == 500
    assert "error" in captured["payload"]


def test_jaeger_chat_uses_a_fresh_mcp_session_per_turn(monkeypatch):
    from jaeger_ai.core.gateway import native_mcp as jaeger
    created = []
    host = jaeger.MCPClient("http://127.0.0.1:8811/mcp", "key", "127.0.0.1:8811")

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            created.append(self)
            self.calls = []

        def initialize(self):
            self.calls.append("initialize")
            return {}

        def _execute_call(self, name, arguments):
            self.calls.append((name, arguments))
            return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(jaeger, "MCPClient", FakeWorker)

    result = host.chat("hello", "table-1")

    assert result["content"][0]["text"] == "ok"
    assert len(created) == 1
    assert created[0].calls == ["initialize", ("chat", {"message": "hello", "session_id": "table-1"})]


def test_jaeger_host_adapter_uses_native_mcp_by_default(monkeypatch):
    from jaeger_ai.core.gateway import native_mcp as jaeger
    monkeypatch.delenv("JAEGERS_MCP_API_KEY", raising=False)

    client = jaeger.current_mcp_client()

    assert client.base_url == "http://127.0.0.1:8792/mcp"
    assert client.host_header == "127.0.0.1:8792"
    # Jaeger's MCP server requires a caller token; jaegerd presents its own.
    from jaeger_ai.core.gateway.caller_auth import read_token
    assert client._headers()["Authorization"] == f"Bearer {read_token('jaegerd')}"


def test_jaeger_nonstream_completion_returns_openai_json(monkeypatch):
    monkeypatch.setattr(
        jaeger,
        "current_mcp_client",
        lambda: SimpleNamespace(chat=lambda _message, _session_id=None: {
            "content": [{"type": "text", "text": "READY"}],
        }),
    )
    handler = object.__new__(jaeger.RunHandler)
    body = json.dumps({
        "stream": False,
        "messages": [{"role": "user", "content": "test"}],
    }).encode()
    handler.headers = {
        "Content-Length": str(len(body)),
        "X-Hermes-Session-Id": "session-1",
    }
    from io import BytesIO
    handler.rfile = BytesIO(body)
    captured = {}
    handler._send_json = lambda status, payload: captured.update(status=status, payload=payload)

    handler._handle_chat_completions()

    assert captured["status"] == 200
    assert captured["payload"]["object"] == "chat.completion"
    assert captured["payload"]["choices"][0]["message"]["content"] == "READY"


def test_jaeger_retry_classifier_does_not_replay_client_errors():
    from jaeger_ai.core.gateway import native_mcp as jaeger
    from urllib.error import HTTPError

    assert not jaeger._is_transient_http(HTTPError("http://mcp", 400, "bad", {}, None))
    assert not jaeger._is_transient_http(HTTPError("http://mcp", 404, "missing", {}, None))
    assert jaeger._is_transient_http(HTTPError("http://mcp", 503, "busy", {}, None))


def test_mcp_key_is_resolved_after_import_and_ignores_the_legacy_ares_key(monkeypatch):
    from jaeger_ai.core.gateway import native_mcp as jaeger
    from jaeger_ai.core.gateway.caller_auth import read_token
    monkeypatch.delenv("JAEGERS_MCP_API_KEY", raising=False)
    monkeypatch.setenv("MCP_ARES_HOST_API_KEY", "stale-ares-key")
    assert jaeger.mcp_api_key() == read_token("jaegerd")
    monkeypatch.setenv("JAEGERS_MCP_API_KEY", "late-env-key")
    assert jaeger.mcp_api_key() == "late-env-key"






































