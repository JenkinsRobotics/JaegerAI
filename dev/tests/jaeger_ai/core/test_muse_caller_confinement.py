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
