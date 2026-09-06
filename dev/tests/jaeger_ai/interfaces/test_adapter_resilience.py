import asyncio
import importlib
import json
import threading
import time
from io import BytesIO

import pytest

from jaeger_ai.interfaces.hermes_profile_adapters import jaeger, openclaw, roundtable
from jaeger_ai.interfaces.hermes_profile_adapters.resilience import CircuitBreaker, CircuitOpen, timeout_setting
from jaeger_ai.interfaces.mcp_server import build_server


def test_mcp_sync_chat_does_not_starve_other_requests():
    entered, release = threading.Event(), threading.Event()

    class Bridge:
        def turn(self, message, session):
            entered.set()
            release.wait(2)
            return {"text": "READY"}

    server = build_server(None, "test", "test", bridge=Bridge())

    async def check():
        task = asyncio.create_task(server.call_tool("chat", {"message": "hello"}))
        try:
            deadline = time.monotonic() + 3
            while not entered.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.005)
            assert entered.is_set()
            assert not task.done(), "sync chat blocked MCP event loop until completion"
            tools = await asyncio.wait_for(server.list_tools(), 0.5)
            assert any(tool.name == "chat" for tool in tools)
        finally:
            release.set()
            await task

    asyncio.run(check())


def test_mcp_http_initialize_during_long_tool_call():
    """Exercise real MCP HTTP/SSE, not only the async tool wrapper."""
    import socket
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

    entered, release = threading.Event(), threading.Event()
    class Bridge:
        def turn(self, message, session):
            entered.set()
            release.wait(3)
            return {"text": "READY"}
    mcp = build_server(None, "test", "test", bridge=Bridge())
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}/mcp"
    server = uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(), log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 3
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)

    async def check():
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                task = asyncio.create_task(session.call_tool("chat", {"message": "test"}))
                try:
                    deadline = time.monotonic() + 2
                    while not entered.is_set() and time.monotonic() < deadline:
                        await asyncio.sleep(0.005)
                    assert entered.is_set()
                    async with streamablehttp_client(url) as (read2, write2, _):
                        async with ClientSession(read2, write2) as other:
                            await asyncio.wait_for(other.initialize(), 0.75)
                            await asyncio.wait_for(other.list_tools(), 0.75)
                            assert not task.done(), "initialize waited for tool completion"
                finally:
                    release.set()
                    await task
    try:
        assert server.started
        asyncio.run(check())
    finally:
        release.set()
        server.should_exit = True
        thread.join(5)
        listener.close()


def test_timeout_results_cannot_be_mutated_by_late_workers(monkeypatch):
    release, finished = threading.Event(), threading.Event()
    def slow(*args):
        release.wait(1)
        finished.set()
        return "LATE ANSWER MUST NOT APPEAR"
    monkeypatch.setattr(roundtable, "chat_jaeger", slow)
    monkeypatch.setattr(roundtable, "MEMBER_TIMEOUT", 0.02)
    output = []
    result = roundtable._parallel_turns({"jaeger": "test"}, output.append, "test", "late-test")
    snapshot = dict(result)
    # The same native session cannot be launched again while its worker runs.
    busy = roundtable._parallel_turns({"jaeger": "retry"}, output.append, "retry", "late-test")
    assert busy["jaeger"].error_category == "busy"
    release.set()
    assert finished.wait(1)
    time.sleep(0.02)
    assert result == snapshot
    assert result["jaeger"].error_category == "timeout"
    assert "LATE ANSWER" not in "".join(output)


@pytest.mark.parametrize("text", ["Error: timed out", "[Jaeger error: HTTP 404]", "(agent error: stopped)", "⚠️ No response (timeout)", "LLM request timed out."])
def test_error_prefixes_are_failures(text):
    assert roundtable._is_failed_answer(text)


def test_prose_about_errors_is_not_a_failure():
    assert not roundtable._is_failed_answer("The previous error: timeout is now resolved. There was no response earlier.")


def test_peer_context_is_bounded_and_truncation_disclosed():
    result = roundtable._peer_transcript({name: "x" * 100000 for name in roundtable.AGENT_ORDER})
    assert len(result) <= roundtable.SHARED_CONTEXT_CHARS
    assert result.count("truncated") == 3


def test_jaeger_import_never_connects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network I/O at import time")
    monkeypatch.setattr(jaeger.urllib.request, "urlopen", forbidden)
    importlib.reload(jaeger)


def test_timeout_setting_finite_and_configurable(monkeypatch):
    monkeypatch.delenv("TEST_ADAPTER_TIMEOUT", raising=False)
    assert timeout_setting("TEST_ADAPTER_TIMEOUT") == 300
    for invalid in ["0", "-1", "nan", "inf"]:
        monkeypatch.setenv("TEST_ADAPTER_TIMEOUT", invalid)
        with pytest.raises(ValueError):
            timeout_setting("TEST_ADAPTER_TIMEOUT")


def test_circuit_breaker_recovers(monkeypatch):
    from jaeger_ai.interfaces.hermes_profile_adapters import resilience
    now = [0.0]
    monkeypatch.setattr(resilience.time, "monotonic", lambda: now[0])
    breaker = CircuitBreaker(threshold=2, cooldown=10)
    breaker.failure()
    breaker.failure()
    with pytest.raises(CircuitOpen):
        breaker.check()
    now[0] = 11
    breaker.check()
    breaker.success()
    assert breaker.failures == 0


def test_jaeger_never_replays_dispatched_chat(monkeypatch):
    client = jaeger.MCPClient("http://example.test/mcp", "", "example.test")
    calls = []
    monkeypatch.setattr(jaeger.MCPClient, "initialize", lambda self: {})
    def fail(*args):
        calls.append(1)
        raise TimeoutError("response lost")
    monkeypatch.setattr(jaeger.MCPClient, "_execute_call", fail)
    with pytest.raises(TimeoutError):
        client.chat("test", "session")
    assert len(calls) == 1


def test_jaeger_stale_session_reinitializes_once(monkeypatch):
    import urllib.error
    client = jaeger.MCPClient("http://example.test/mcp", "", "example.test")
    client._session_id = "expired"
    initializations, sessions = [], []
    def initialize():
        initializations.append(1)
        client._session_id = "fresh"
    def call(*args):
        sessions.append(client._session_id)
        if client._session_id == "expired":
            raise urllib.error.HTTPError(client.base_url, 404, "session not found", {}, None)
        return {"content": []}
    monkeypatch.setattr(client, "initialize", initialize)
    monkeypatch.setattr(client, "_execute_call", call)
    client.call_tool("agent_info", {})
    assert sessions == ["expired", "fresh"]
    assert initializations == [1]


def test_mcp_json_and_sse_responses():
    client = jaeger.MCPClient("http://example.test/mcp", "", "example.test")
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
    encoded = json.dumps(payload).encode()
    assert client._parse_sse(encoded) == [payload]
    assert client._parse_sse(b"data: " + encoded + b"\n\n") == [payload]


def test_all_failed_members_do_not_create_a_consensus(monkeypatch):
    calls = []
    def fail(*args):
        calls.append(1)
        return "Error: upstream timed out"
    for name in ["chat_hermes", "chat_jaeger", "chat_openclaw"]:
        monkeypatch.setattr(roundtable, name, fail)
    output = []
    roundtable.run_debate_stream("hello", output.append, "all-failed-test")
    assert len(calls) == 3
    assert "No consensus was reached" in "".join(output)


def test_openclaw_hang_returns_structured_timeout(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("test-not-a-real-secret")
    monkeypatch.setattr(openclaw, "OPENCLAW_TOKEN_FILE", token)
    monkeypatch.setattr(openclaw, "REQUEST_TIMEOUT", 0.03)
    monkeypatch.setattr(openclaw, "_circuit", CircuitBreaker())
    def hang(request, timeout):
        assert timeout == 0.03
        raise TimeoutError("upstream stalled")
    monkeypatch.setattr(openclaw.urllib.request, "urlopen", hang)
    handler = object.__new__(openclaw.Handler)
    body = json.dumps({"messages": [{"role": "user", "content": "test"}]}).encode()
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body)
    responses = []
    handler.send_json = lambda status, data: responses.append((status, data))
    handler.create_chat_completion()
    assert responses[0][0] == 504
    assert responses[0][1]["error"]["type"] == "timeout"
