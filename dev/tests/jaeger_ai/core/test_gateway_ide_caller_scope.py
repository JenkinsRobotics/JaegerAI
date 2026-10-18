"""The IDE Chat tab's ``ide`` caller (owner:ide) covers the chat routes it uses."""
from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.caller_auth import CALLERS, client_headers, required_scope
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

IDE_ROUTES = [
    ("GET", "/v1/sessions", "read"),
    ("POST", "/v1/sessions", "turn"),
    ("GET", "/v1/sessions/{id}/stream", "read"),
    ("POST", "/v1/approvals/{id}", "approve"),
    ("POST", "/v1/sessions/{id}/turns", "turn"),
]


@pytest.mark.parametrize("method,route,scope", IDE_ROUTES)
def test_ide_scopes_cover_chat_routes(method, route, scope):
    assert required_scope(method, route) == scope
    assert scope in CALLERS["ide"].scopes
    assert CALLERS["ide"].session_prefix is None  # reads/writes every owner session


@pytest.mark.asyncio
async def test_ide_token_passes_the_middleware_on_each_route(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    approval = gateway.store.create_approval(kind="tool", prompt="Allow?", options=["once", "deny"],
                                             session_id="ide-chat")
    async with TestClient(TestServer(gateway.app), headers=client_headers("ide")) as client:
        created = await client.post("/v1/sessions", json={"session_id": "ide-chat", "title": "IDE"})
        assert created.status in (200, 201)
        listed = await client.get("/v1/sessions")
        assert listed.status == 200
        assert "ide-chat" in [s["session_id"] for s in (await listed.json())["sessions"]]
        gateway.event_bus.publish("ide-chat", "session.updated", {"session": {}})
        stream = await client.get("/v1/sessions/ide-chat/stream")
        assert stream.status == 200
        assert (await asyncio.wait_for(stream.content.readuntil(b"\n\n"), 5)).startswith(b"id: ")
        stream.close()
        resolved = await client.post(f"/v1/approvals/{approval['approval_id']}", json={"decision": "once"})
        assert resolved.status == 200
        # Auth passes on the turn route: an empty body is refused by the handler, not the middleware.
        turn = await client.post("/v1/sessions/ide-chat/turns", json={})
        assert turn.status not in (401, 403)
    async with TestClient(TestServer(gateway.app)) as client:
        assert (await client.get("/v1/sessions")).status == 401
