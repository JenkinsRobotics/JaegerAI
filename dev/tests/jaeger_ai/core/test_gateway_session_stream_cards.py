"""One session stream carries thinking, tools, approvals and handoffs, and the
approval answer endpoint resolves the parked card (native chat surfaces)."""
from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.mark.asyncio
async def test_session_stream_carries_reasoning_tool_approval_and_handoff(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    gateway.store.ensure_session("chat")
    callbacks, finish = gateway._turn_stream_callbacks("chat", "r1")
    callbacks.reasoning("considering")
    callbacks.tool_progress("read_file", "start", {"path": "a.py"})
    callbacks.tool_done("read_file", {"path": "a.py"}, "ok", True, None, 0.01)
    callbacks.stream_delta("Done.")
    finish()
    approval = gateway.store.create_approval(kind="tool_confirm", prompt="Allow files.write_file?",
                                             options=["once", "session", "deny"], session_id="chat",
                                             request_id="r1")
    gateway.event_bus.publish("chat", "approval.request", {
        "approval_id": approval["approval_id"], "kind": "tool", "prompt": "Allow files.write_file?",
        "options": ["once", "session", "deny"], "session_id": "chat", "request_id": "r1"})
    agent_id = gateway._registry().list_agents(role="specialist")[0].id
    async with TestClient(TestServer(gateway.app), headers=client_headers("ide")) as client:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        gateway.pending_approvals[approval["approval_id"]] = future
        resolved = await client.post(f"/v1/approvals/{approval['approval_id']}", json={"decision": "session"})
        assert resolved.status == 200 and future.result() is True
        assert (await client.post("/v1/sessions/chat/handoff", json={"to_agent_id": agent_id})).status == 200
        stream = await client.get("/v1/sessions/chat/stream?last_event_id=0")
        assert stream.status == 200
        want = {"turn.reasoning", "turn.reasoning.done", "tool.started", "tool.completed", "turn.delta",
                "approval.request", "approval.resolved", "session.handoff"}
        seen: dict[str, dict] = {}
        while not want <= set(seen):
            try:
                frame = (await asyncio.wait_for(stream.content.readuntil(b"\n\n"), 3)).decode()
            except TimeoutError:
                break
            body = json.loads(frame.split("data: ", 1)[1])
            seen.setdefault(body["event"], body["data"])
        stream.close()
    assert want <= set(seen), sorted(seen)
    assert seen["approval.request"]["options"] == ["once", "session", "deny"]
    assert seen["approval.resolved"]["approval_id"] == approval["approval_id"]
    assert seen["session.handoff"]["to_agent_id"] == agent_id
    assert seen["tool.started"]["request_id"] == "r1" and seen["turn.reasoning.done"]["duration_ms"] >= 0
