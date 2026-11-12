import asyncio
import importlib
import json
import threading
import time
from io import BytesIO

import pytest

from jaeger_ai.core.frameworks.resilience import CircuitBreaker, CircuitOpen, timeout_setting
from jaeger_ai.interfaces.mcp_server import build_server


def test_mcp_sync_chat_does_not_starve_other_requests():
    entered, release = threading.Event(), threading.Event()

    class Bridge:
        def turn(self, message, session, **kwargs):
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
        def turn(self, message, session, **kwargs):
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












def test_timeout_setting_finite_and_configurable(monkeypatch):
    monkeypatch.delenv("TEST_ADAPTER_TIMEOUT", raising=False)
    assert timeout_setting("TEST_ADAPTER_TIMEOUT") == 300
    for invalid in ["0", "-1", "nan", "inf"]:
        monkeypatch.setenv("TEST_ADAPTER_TIMEOUT", invalid)
        with pytest.raises(ValueError):
            timeout_setting("TEST_ADAPTER_TIMEOUT")


def test_circuit_breaker_recovers(monkeypatch):
    from jaeger_ai.core.frameworks import resilience
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










