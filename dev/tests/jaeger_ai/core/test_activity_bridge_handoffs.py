"""Inbox handoffs between apps (handoff_task to a peer, post_result back) appear in
GET /v1/activity as handoff.sent / handoff.result; grokbot may read the feed."""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


@pytest_asyncio.fixture
async def hub(tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_MCP_TOKEN_FILE", raising=False)
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    tokens = tmp_path / "tokens"
    tokens.mkdir(mode=0o700)
    for name in ("grokbot", "ares", "webui"):  # throwaway 0600 tokens in a temp dir, never the Keychain
        (tokens / f"{name}.token").write_text(f"test-{name}-token-{tmp_path.name}")
        (tokens / f"{name}.token").chmod(0o600)
    monkeypatch.setenv("JAEGER_CALLER_TOKEN_DIR", str(tokens))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "sessions.sqlite3"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app)) as client:
        loop = asyncio.get_running_loop()

        def app_client(name):
            class C:
                def _call(self, method, path, body=None):
                    async def go():
                        r = await client.request(method, path, json=body, headers=caller_auth.client_headers(name))
                        assert r.status < 400, (path, r.status, await r.text())
                        return await r.json()
                    return asyncio.run_coroutine_threadsafe(go(), loop).result(10)
            return C()

        from jaeger_ai.features.agent_bridge import mcp as bridge_mcp
        tools = {}
        for name in ("grokbot", "ares"):
            fake = _FakeMCP()
            bridge_mcp.register(fake, lambda ctx, n=name: app_client(n))
            tools[name] = fake.tools
        yield client, gateway, tools


async def _activity(client, who="webui", **q):
    r = await client.get("/v1/activity", params=q, headers=caller_auth.client_headers(who))
    assert r.status == 200, await r.text()
    return (await r.json())["items"]


@pytest.mark.asyncio
async def test_handoff_sent_and_result_rows(hub):
    client, gateway, tools = hub
    out = await tools["grokbot"]["handoff_task"](to="ares", task="build the thing", title="Build", thread="t-ga", id="h-ga")
    assert out["kind"] == "message"
    await tools["ares"]["post_result"](to="grokbot", thread="t-ga", body="built", title="Built")
    # idempotent redelivery of the same handoff adds no second row
    await tools["grokbot"]["handoff_task"](to="ares", task="build the thing", title="Build", thread="t-ga", id="h-ga")

    items = [i for i in await _activity(client) if i["kind"].startswith("handoff.")]
    by_kind = {i["kind"]: i for i in items}
    assert len(items) == 2 and set(by_kind) == {"handoff.sent", "handoff.result"}
    sent, res = by_kind["handoff.sent"], by_kind["handoff.result"]
    assert sent["data"]["caller"] == {"caller_id": "grokbot", "caller_kind": "mcp"}
    assert sent["data"]["recipient"] == "ares" and sent["data"]["handoff_id"] == "h-ga"
    assert sent["data"]["status"] == "handoff" and sent["actor_id"] == "grokbot" and sent["agent_id"] == "ares"
    assert sent["summary"] == "grokbot handed off h-ga to ares: Build"
    assert res["data"]["caller"]["caller_id"] == "ares" and res["data"]["recipient"] == "grokbot"
    assert res["data"]["handoff_id"] == "h-ga" and res["data"]["status"] == "done"
    assert res["refs"]["handoff_id"] == "h-ga" and res["refs"]["thread"] == "t-ga"
    assert res["session_id"] == "*"
    # event_id is the global "*" stream id
    with gateway.store._immediate() as conn:
        ev = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT event_id, event, session_id FROM events")}
    assert ev[sent["event_id"]] == ("handoff.sent", "*") and ev[res["event_id"]] == ("handoff.result", "*")
    # filter by app
    assert {i["kind"] for i in await _activity(client, agent_id="ares") if i["kind"].startswith("handoff.")} == {
        "handoff.sent", "handoff.result"}
    # handoff_task(to="jaeger") stays a goal row only (no duplicate handoff.sent for jaegerd)
    await tools["grokbot"]["send_message"](id="m-j", thread="t-j", to="jaegerd", kind="task", title="x", body="y")
    assert not [i for i in await _activity(client) if i["kind"] == "handoff.sent" and i["data"]["recipient"] == "jaegerd"]
    print("ROW handoff.sent", json.dumps(sent, indent=1))
    print("ROW handoff.result", json.dumps(res, indent=1))


@pytest.mark.asyncio
async def test_grokbot_reads_activity_read_only(hub):
    client, gateway, tools = hub
    h = caller_auth.client_headers("grokbot")
    saved = caller_auth.CALLER_READ_ROUTES
    caller_auth.CALLER_READ_ROUTES = {}  # before this change
    try:
        assert (await client.get("/v1/activity", headers=h)).status == 403
    finally:
        caller_auth.CALLER_READ_ROUTES = saved
    assert (await client.get("/v1/activity", headers=h)).status == 200
    # only grokbot, only GET /v1/activity
    assert (await client.get("/v1/activity", headers=caller_auth.client_headers("ares"))).status == 403
    assert (await client.get("/v1/approvals", headers=h)).status == 403
    assert (await client.post("/v1/handoffs/x/check", json={"state": "passed"}, headers=h)).status == 403
    assert caller_auth.prefixed_route_allowed("GET", "/v1/activity", "grokbot")
    assert not caller_auth.prefixed_route_allowed("GET", "/v1/activity")
    assert not caller_auth.prefixed_route_allowed("POST", "/v1/activity", "grokbot")
