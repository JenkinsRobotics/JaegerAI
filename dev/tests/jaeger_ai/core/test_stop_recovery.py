"""Isolated Stop recovery and MCP cancellation contracts; no servers/models."""
import asyncio
import json
import threading
from types import SimpleNamespace

import pytest


def test_recovered_session_exposes_only_latest_admitted_control_identity(tmp_path):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    store = GatewaySessionStore(tmp_path / "gateway.sqlite3")
    store.admit_request("s", "private prompt", request_id="active")
    store.enqueue_request("s", "later work", request_id="queued")
    app = SimpleNamespace(store=store, _enrich_session_agent=lambda session: dict(session))
    request = SimpleNamespace(match_info={"id": "s"}, query={"view": "control"})
    response = asyncio.run(JaegerGatewayApp.handle_get_session(app, request))
    payload = json.loads(response.body)
    assert set(payload) == {"session_id", "status", "latest_request"}
    control = payload["latest_request"]
    assert control["request_id"] == "active"
    assert control["status"] == "admitted"
    assert "input_text" not in control and "output" not in control
    assert store.get_request("queued")["status"] == "queued"


def _registry():
    from jaeger_ai.plugins.mcp.client import MCPRegistry, MCPToolSpec, MCPServerConfig
    registry = MCPRegistry()
    registry._tools["mcp:fixture/work"] = MCPToolSpec("mcp:fixture/work", "fixture", "work", "", {})
    config = MCPServerConfig(name="fixture", call_timeout_s=1)
    return registry, config


def test_mcp_interrupt_cancels_only_its_future_without_retry():
    from jaeger_agent.core.cancellation import turn_cancellation
    registry, config = _registry()
    started, cancelled, interrupt = threading.Event(), threading.Event(), threading.Event()
    calls = []
    async def call(*args):
        calls.append(args)
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    registry._clients["fixture"] = SimpleNamespace(config=config, call=call)
    other = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05, result="unrelated"), registry._loop)
    timer = threading.Timer(0.03, interrupt.set)
    timer.start()
    try:
        with turn_cancellation(interrupt), pytest.raises(RuntimeError, match="remote outcome unconfirmed"):
            registry.call("mcp:fixture/work", {})
        assert started.is_set() and cancelled.wait(1)
        assert len(calls) == 1
        assert other.result(timeout=1) == "unrelated"
    finally:
        timer.join()
        registry._loop.call_soon_threadsafe(registry._loop.stop)
        registry._loop_thread.join(timeout=1)
        registry._loop.close()


def test_mcp_timeout_does_not_replay_an_uncertain_call():
    registry, config = _registry()
    calls, cancelled = [], threading.Event()
    async def call(*args):
        calls.append(args)
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    registry._clients["fixture"] = SimpleNamespace(config=config, call=call)
    try:
        with pytest.raises(RuntimeError, match="remote outcome unconfirmed"):
            registry.call("mcp:fixture/work", {}, timeout=0.02)
        assert cancelled.wait(1)
        assert len(calls) == 1
    finally:
        registry._loop.call_soon_threadsafe(registry._loop.stop)
        registry._loop_thread.join(timeout=1)
        registry._loop.close()
