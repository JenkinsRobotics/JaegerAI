"""Handoffs are linked to their chat session and readable as one exchange.

Agents View spec #3 (filters) and #9 (``/v1/handoffs/{id}/messages``).
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def _handoff(store, hid, to_agent, *, parent=None, session_id=None, status="completed", result=None):
    return store.save_handoff({
        "id": hid, "request_id": f"req-{hid}", "from_agent_id": "native:jaeger", "to_agent_id": to_agent,
        "parent_run_id": parent, "task": f"task for {hid}", "status": status,
        "require_approval": False, "result": result or {}, "metadata": {}, "session_id": session_id,
    })


@pytest.fixture
def store(tmp_path):
    return GatewaySessionStore(tmp_path / "handoffs.sqlite3")


def test_store_records_and_resolves_session(store):
    store.ensure_session("chat-1", title="chat")
    store.admit_request("chat-1", "hello", request_id="run-1")
    _handoff(store, "h_direct", "native:gateway", session_id="chat-9")
    _handoff(store, "h_parent", "native:surfaces", parent="run-1")
    _handoff(store, "h_none", "native:everyday")
    by_id = {h["id"]: h for h in store.list_handoffs()}
    assert by_id["h_direct"]["session_id"] == "chat-9"
    assert by_id["h_parent"]["session_id"] == "chat-1"  # resolved through client_requests
    assert by_id["h_none"]["session_id"] is None
    assert [h["id"] for h in store.list_handoffs(session_id="chat-1")] == ["h_parent"]
    assert [h["id"] for h in store.list_handoffs(agent_id="native:gateway")] == ["h_direct"]
    assert len(store.list_handoffs(agent_id="native:jaeger")) == 3  # either end matches
    assert len(store.list_handoffs(limit=2)) == 2
    assert store.list_handoffs(since=time.time() + 60) == []


def test_session_id_is_kept_on_update(store):
    _handoff(store, "h1", "native:gateway", session_id="chat-1", status="admitted")
    _handoff(store, "h1", "native:gateway", session_id=None, status="running")
    assert store.get_handoff("h1")["session_id"] == "chat-1"


@pytest_asyncio.fixture
async def client(store):
    gateway = JaegerGatewayApp(store=store)
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as c:
        yield c


@pytest.mark.asyncio
async def test_list_filters_and_bad_query(client, store):
    _handoff(store, "h_a", "native:gateway", session_id="s1")
    _handoff(store, "h_b", "native:surfaces", session_id="s2")
    body = await (await client.get("/v1/handoffs?session_id=s1")).json()
    assert body["count"] == 1 and body["handoffs"][0]["id"] == "h_a"
    body = await (await client.get("/v1/handoffs?agent_id=native:surfaces&limit=5")).json()
    assert [h["id"] for h in body["handoffs"]] == ["h_b"]
    assert (await client.get("/v1/handoffs?limit=0")).status == 400
    assert (await client.get("/v1/handoffs?since=yesterday")).status == 400


@pytest.mark.asyncio
async def test_handoff_messages_returns_the_exchange(client, store):
    worker = "specialist:native:gateway:req-h_m"
    store.ensure_session(worker, title="worker")
    store.append_message(worker, "user", "do the thing")
    store.append_message(worker, "assistant", "did it")
    _handoff(store, "h_m", "native:gateway", session_id="s1",
             result={"ok": True, "summary": "done", "worker_session_id": worker})
    resp = await client.get("/v1/handoffs/h_m/messages")
    assert resp.status == 200
    body = await resp.json()
    assert body["worker_session_id"] == worker and body["summary"] == "done"
    assert body["task"] == "task for h_m" and body["session_id"] == "s1"
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "do the thing"), ("assistant", "did it")]
    assert set(body["messages"][0]) == {"id", "role", "content", "timestamp"}


@pytest.mark.asyncio
async def test_handoff_messages_default_worker_session_and_404(client, store):
    _handoff(store, "h_n", "native:surfaces")
    body = await (await client.get("/v1/handoffs/h_n/messages")).json()
    assert body["worker_session_id"] == "specialist:native:surfaces:req-h_n" and body["messages"] == []
    assert (await client.get("/v1/handoffs/nope/messages")).status == 404


@pytest.mark.asyncio
async def test_handoff_routes_need_token_and_refuse_prefixed_callers(store):
    gateway = JaegerGatewayApp(store=store)
    gateway.app.on_startup.clear()
    _handoff(store, "h_x", "native:gateway")
    async with TestClient(TestServer(gateway.app)) as anon:
        assert (await anon.get("/v1/handoffs/h_x/messages")).status == 401
        assert (await anon.get("/v1/handoffs/h_x/messages", headers=client_headers("mcp"))).status == 403
