"""Muse may use the hub and backlog without gaining agent execution routes."""

from __future__ import annotations

import asyncio

import pytest

from jaeger_ai.core.gateway.caller_auth import CALLER_ONLY_ROUTES, prefixed_route_allowed


MUSE_ALLOWED = {
    ("GET", "/v1/agent-messages"), ("GET", "/v1/agent-threads/{thread}"),
    ("POST", "/v1/agent-messages"), ("GET", "/v1/agents"),
    ("GET", "/v1/approvals/counts"), ("GET", "/v1/agent-goals/{goal_id}"),
    ("GET", "/v1/backlog"), ("GET", "/v1/backlog/sweep"),
    ("POST", "/v1/backlog"), ("POST", "/v1/backlog/{id}"),
    ("POST", "/v1/backlog/{id}/assign"),
}


def test_muse_exact_gateway_routes():
    assert CALLER_ONLY_ROUTES["muse"] == MUSE_ALLOWED
    for method, route in MUSE_ALLOWED:
        assert prefixed_route_allowed(method, route, "muse")
    for method, route in [
        ("POST", "/v1/sessions"), ("POST", "/v1/sessions/{id}/turns"),
        ("POST", "/v1/agent-goals"), ("POST", "/v1/models/generate"),
        ("POST", "/v1/models/route"), ("POST", "/v1/search"),
        ("POST", "/v1/backlog/import"), ("POST", "/v1/apps/{app}/proposals"),
    ]:
        assert not prefixed_route_allowed(method, route, "muse")


def test_other_callers_keep_their_routes():
    for caller in ("ares", "grokbot"):
        for method, route in [
            ("POST", "/v1/sessions/{id}/turns"), ("POST", "/v1/agent-goals"),
            ("POST", "/v1/models/generate"), ("POST", "/v1/agent-messages"),
            ("GET", "/v1/backlog"),
        ]:
            assert prefixed_route_allowed(method, route, caller)
    for method, route in CALLER_ONLY_ROUTES["rackpc"]:
        assert prefixed_route_allowed(method, route, "rackpc")
    assert not prefixed_route_allowed("POST", "/v1/agent-goals", "rackpc")


class _MCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name=None):
        def register(fn):
            self.tools[name or fn.__name__] = fn
            return fn
        return register


class _Client:
    def __init__(self, caller):
        self.caller = caller
        self.calls = []

    def _call(self, method, route, body=None):
        from urllib.parse import urlsplit
        from jaeger_ai.core.gateway.caller_auth import prefixed_route_allowed
        path = urlsplit(route).path
        template = path
        if path.startswith("/v1/agent-threads/"):
            template = "/v1/agent-threads/{thread}"
        elif path.startswith("/v1/agent-goals/"):
            template = "/v1/agent-goals/{goal_id}"
        elif path.startswith("/v1/backlog/") and path not in ("/v1/backlog/sweep", "/v1/backlog/import"):
            template = "/v1/backlog/{id}/assign" if path.endswith("/assign") else "/v1/backlog/{id}"
        if not prefixed_route_allowed(method, template, self.caller):
            raise PermissionError("Gateway refused route")
        self.calls.append((method, route, body))
        return {"ok": True}


def test_mcp_muse_tools_and_other_callers():
    from jaeger_ai.features.agent_bridge import mcp as bridge_mcp

    for caller in ("muse", "rackpc", "ares", "grokbot"):
        mcp, client = _MCP(), _Client(caller)
        bridge_mcp.register(mcp, lambda ctx: client)
        args = dict(id="x", thread="t", to="ares", kind="note", title="t", body="b")
        if caller == "muse":
            with pytest.raises(PermissionError):
                asyncio.run(mcp.tools["send_message"](**args))
        else:
            asyncio.run(mcp.tools["send_message"](**args))
        if caller == "muse":
            with pytest.raises(PermissionError):
                asyncio.run(mcp.tools["start_goal"](goal="g", workspace_folder="/tmp", thread="t", id="g"))
            with pytest.raises(PermissionError):
                asyncio.run(mcp.tools["jaeger.generate"](prompt="hi"))
            asyncio.run(mcp.tools["post_result"](to="ares", thread="t", body="done"))
            asyncio.run(mcp.tools["jaeger.backlog_list"]())
            asyncio.run(mcp.tools["jaeger.backlog_update"](id="J-1", status="open"))
        assert client.calls


def test_mcp_chat_refuses_muse_before_turn(monkeypatch):
    from jaeger_ai.interfaces import mcp_server

    class Bridge:
        called = False

        def turn(self, *args, **kwargs):
            self.called = True
            return {"text": "unexpected"}

    bridge = Bridge()
    monkeypatch.setattr(mcp_server, "_presented_caller", lambda ctx: ("muse", "proved-token"))
    server = mcp_server.build_server(None, "test", None, bridge=bridge)
    with pytest.raises(Exception):
        asyncio.run(server.call_tool("chat", {"message": "hello"}))
    assert not bridge.called


@pytest.mark.parametrize("tool,args", [
    ("agent_info", {}), ("capability_inventory_tool", {}),
    ("bridge_health", {}), ("bridge_query", {"what": "identity"}),
    ("list_delegates", {}), ("cancel_turn", {"request_id": "turn-1"}),
])
def test_mcp_muse_refused_before_bridge_access(monkeypatch, tool, args):
    from jaeger_ai.interfaces import mcp_server

    class Bridge:
        def __init__(self):
            self.calls = []

        def query(self, *args, **kwargs):
            self.calls.append("query")
            return {}

        def health(self):
            self.calls.append("health")
            return {}

        def control(self, *args, **kwargs):
            self.calls.append("control")
            return {}

    bridge = Bridge()
    monkeypatch.setattr(mcp_server, "_presented_caller", lambda ctx: ("muse", "proved-token"))
    server = mcp_server.build_server(None, "test", None, bridge=bridge)
    with pytest.raises(Exception, match="muse"):
        asyncio.run(server.call_tool(tool, args))
    assert bridge.calls == []


def test_mcp_muse_cancel_refused_before_bridge_local_fallback(monkeypatch):
    from jaeger_ai.interfaces import mcp_server

    class Bridge:
        called = False

        def control(self, *args, **kwargs):
            self.called = True

    bridge = Bridge()
    monkeypatch.setattr(mcp_server, "_presented_caller", lambda ctx: ("muse", None))
    server = mcp_server.build_server(None, "test", None, bridge=bridge)
    with pytest.raises(Exception, match="muse"):
        asyncio.run(server.call_tool("cancel_turn", {"request_id": "turn-1"}))
    assert not bridge.called


def test_mcp_other_callers_keep_info_and_bridge_access(monkeypatch):
    from jaeger_ai.interfaces import mcp_server

    class Bridge:
        def __init__(self):
            self.calls = []

        def query(self, name, *args):
            self.calls.append(name)
            return {}

        def health(self):
            self.calls.append("health")
            return {"ok": True}

        def control(self, *args, **kwargs):
            self.calls.append("control")

    for caller in ("ares", "grokbot", "rackpc"):
        bridge = Bridge()
        monkeypatch.setattr(mcp_server, "_presented_caller", lambda ctx, caller=caller: (caller, None))
        server = mcp_server.build_server(None, "test", None, bridge=bridge)
        for tool, args in [
            ("agent_info", {}), ("capability_inventory_tool", {}),
            ("bridge_health", {}), ("bridge_query", {"what": "identity"}),
            ("list_delegates", {}), ("cancel_turn", {"request_id": "turn-1"}),
        ]:
            asyncio.run(server.call_tool(tool, args))
        assert "control" in bridge.calls
        assert "health" in bridge.calls


def test_muse_cannot_bypass_send_refusal_with_handoff_alias():
    from jaeger_ai.features.agent_bridge import mcp as bridge_mcp
    mcp, client = _MCP(), _Client('muse')
    bridge_mcp.register(mcp, lambda ctx: client)
    for recipient in ('ares', 'jaeger'):
        with pytest.raises(PermissionError, match='muse'):
            asyncio.run(mcp.tools['handoff_task'](to=recipient, task='do work', workspace_folder='/tmp'))
    assert client.calls == []


@pytest.mark.asyncio
async def test_authenticated_muse_http_cannot_admit_work(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'gateway.sqlite3'))
    gateway.app.on_startup.clear()
    headers = client_headers('muse')
    async with TestClient(TestServer(gateway.app)) as http:
        for path in ('/v1/sessions', '/v1/sessions/muse:test/turns', '/v1/agent-goals', '/v1/models/generate', '/v1/backlog/import'):
            response = await http.post(path, json={}, headers=headers)
            assert response.status == 403, path
