import json
import threading

import pytest
from jaeger_agent.adapters.ollama import OllamaAdapter
from jaeger_agent.adapters.openai import OpenAIAdapter


def adapter(**kwargs):
    return OllamaAdapter(provider="ollama", model="local-fixture", num_ctx=4096,
                         metadata={"thinking": {"values": [True, False], "default": True}}, **kwargs)


def test_native_options_and_tool_result_identity():
    a = adapter(reasoning_effort="none")
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "name": "lookup", "arguments": {"value": 2}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "lookup", "content": "3"},
    ]
    wire = a.format_messages(messages, [], "system")
    native = a._native_body(wire, a._metadata())
    assert native["options"]["num_ctx"] == 4096
    assert native["think"] is False
    assert native["messages"][1]["tool_calls"][0]["function"]["arguments"] == {"value": 2}
    assert native["messages"][2]["tool_name"] == "lookup"
    assert native["messages"][2]["tool_call_id"] == "c1"
    assert isinstance(wire["messages"][1]["tool_calls"][0]["function"]["arguments"], str)


def test_unsupported_thinking_off_is_not_silently_accepted():
    a = adapter(reasoning_effort="none")
    with pytest.raises(ValueError, match="does not support disabling thinking"):
        a._native_body(a.format_messages([], [], ""), {"thinking": {"values": [True]}})


def test_native_stream_preserves_text_reasoning_tools_usage(monkeypatch):
    a = adapter(reasoning_effort="none")
    captured, text, reasoning = {}, [], []
    rows = [
        {"message": {"thinking": "checking"}, "done": False},
        {"message": {"content": "hello"}, "done": False},
        {"message": {"tool_calls": [{"function": {"name": "lookup", "arguments": {"value": 2}}}]}, "done": False},
        {"model": "local-fixture", "message": {}, "done": True, "done_reason": "stop",
         "prompt_eval_count": 10, "eval_count": 5},
    ]

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self): return (json.dumps(row) for row in rows)

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stream(self, method, url, **kwargs):
            captured.update(url=url, body=kwargs["json"])
            return Response()

    monkeypatch.setattr("httpx.Client", Client)
    raw = a.call(a.format_messages([], [], ""), threading.Event(),
                 on_delta=text.append, on_reasoning=reasoning.append)
    result = a.parse_response(raw)
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["options"]["num_ctx"] == 4096
    assert text == ["hello"] and reasoning == ["checking"]
    assert result["tool_calls"][0]["arguments"] == {"value": 2}
    assert a.last_usage["total_tokens"] == 15


def test_hosted_model_preserves_existing_transport(monkeypatch):
    # 1. Direct ollama.com cloud route skips /api/show metadata probes and strips :cloud for /api/chat.
    direct = OllamaAdapter(
        provider="ollama-cloud", model="kimi-k2.7-code:cloud", base_url="https://ollama.com/api",
    )
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: pytest.fail("Direct ollama.com must not probe /api/show"))
    assert direct._metadata() == {}
    body = direct._native_body(direct.format_messages([], [], ""), direct._metadata())
    assert body["model"] == "kimi-k2.7-code"

    # 2. Local Ollama proxying a remote_host model falls back to OpenAIAdapter._call_once without extra_body.
    proxied = OllamaAdapter(
        provider="ollama", model="kimi-k2.7-code:cloud",
        metadata={"remote_host": "https://ollama.com"},
    )
    captured = []
    monkeypatch.setattr(OpenAIAdapter, "_call_once", lambda self, formatted, *args, **kwargs: captured.append(formatted) or {})
    wire = proxied.format_messages([], [], "")
    proxied.call(wire, threading.Event())
    expected = {k: v for k, v in wire.items() if k != "extra_body"}
    expected.pop("reasoning_effort", None)
    assert captured == [expected]


def test_inline_images_use_native_images_array():
    a = adapter()
    wire = a.format_messages([{"role": "user", "content": [
        {"type": "text", "text": "Describe"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
    ]}], [], "")
    msg = a._native_body(wire, {})["messages"][0]
    assert msg["content"] == "Describe" and msg["images"] == ["YQ=="]
