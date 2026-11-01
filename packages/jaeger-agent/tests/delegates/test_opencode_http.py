import asyncio
from urllib.error import URLError

import pytest

from jaeger_agent.delegates import DelegateRegistry, DelegateRequest, register_builtin_delegates
from jaeger_agent.delegates.opencode.http_runtime import OpenCodeHTTPRuntime


def request():
    return DelegateRequest(task_id="task-1", prompt="Implement it", idempotency_key="key-1")


def test_registration_is_explicit(monkeypatch):
    monkeypatch.delenv("JAEGER_OPENCODE_HTTP_ENABLED", raising=False)
    assert register_builtin_delegates(DelegateRegistry()).get("opencode-http") is None
    monkeypatch.setenv("JAEGER_OPENCODE_HTTP_ENABLED", "true")
    registry = register_builtin_delegates(DelegateRegistry())
    assert isinstance(registry.get("opencode-http"), OpenCodeHTTPRuntime)
    assert registry.get("opencode") is not None


def test_rejects_non_loopback_and_credentials():
    for url in ("https://example.com", "http://192.168.1.2:4096", "http://user:pass@localhost:4096"):
        with pytest.raises(ValueError):
            OpenCodeHTTPRuntime(url)


def test_http_lifecycle(monkeypatch):
    calls = []
    def fake_request(self, method, path, body=None, timeout=5):
        calls.append((method, path, body))
        if path == "/global/health":
            return {"healthy": True}
        if path == "/session":
            return {"id": "ses-1"}
        return {"parts": [{"type": "text", "text": "Done"}], "info": {}}
    monkeypatch.setattr(OpenCodeHTTPRuntime, "_request", fake_request)
    async def run():
        runtime = OpenCodeHTTPRuntime()
        assert (await runtime.probe()).available
        handle = await runtime.start(request())
        assert (await runtime.result(handle)).summary == "Done"
        assert [event.event_type async for event in runtime.stream(handle)] == ["started", "completed"]
    asyncio.run(run())
    assert calls[2] == ("POST", "/session/ses-1/message", {"parts": [{"type": "text", "text": "Implement it"}]})


def test_unavailable_server_is_clean(monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("OpenCode HTTP server is unavailable; start it explicitly before using this delegate")
    monkeypatch.setattr(OpenCodeHTTPRuntime, "_request", unavailable)
    async def run():
        runtime = OpenCodeHTTPRuntime()
        assert not (await runtime.probe()).available
        with pytest.raises(RuntimeError, match="server is unavailable"):
            await runtime.start(request())
    asyncio.run(run())
