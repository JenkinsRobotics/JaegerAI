"""MCP-caller goals (handoff_task(to="jaeger")) appear in GET /v1/activity tagged with the caller."""
from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import agent_activity, caller_auth
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
    monkeypatch.setenv("JAEGER_AGENT_WORKSPACES", json.dumps({"codex": [str(tmp_path)]}))
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    tokens = tmp_path / "tokens"
    tokens.mkdir(mode=0o700)
    for name in ("codex", "webui"):  # throwaway 0600 tokens in a temp dir, never the Keychain
        (tokens / f"{name}.token").write_text(f"test-{name}-token-{tmp_path.name}")
        (tokens / f"{name}.token").chmod(0o600)
    monkeypatch.setenv("JAEGER_CALLER_TOKEN_DIR", str(tokens))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "sessions.sqlite3"))
    gateway.app.on_startup.clear()

    async def deterministic(session_id, turn_id, text, *, request_id=None, execution=None):
        gateway.store.complete_request(request_id, status="completed", result={"output": "done"})
    gateway._execute_turn_inner = deterministic
    async with TestClient(TestServer(gateway.app)) as client:
        loop = asyncio.get_running_loop()

        class Codex:  # the MCP hub's per-app client, speaking as caller "codex"
            def _call(self, method, path, body=None):
                async def go():
                    r = await client.request(method, path, json=body, headers=caller_auth.client_headers("codex"))
                    assert r.status < 400, (path, r.status, await r.text())
                    return await r.json()
                return asyncio.run_coroutine_threadsafe(go(), loop).result(10)

        from jaeger_ai.features.agent_bridge import mcp as bridge_mcp
        fake = _FakeMCP()
        bridge_mcp.register(fake, lambda ctx: Codex())
        yield client, gateway, fake.tools, tmp_path


async def _activity(client, **q):
    r = await client.get("/v1/activity", params=q, headers=caller_auth.client_headers("webui"))
    assert r.status == 200
    return (await r.json())["items"]


async def _wait(pred, gateway, t=5):
    for _ in range(int(t / 0.02)):
        if pred():
            return True
        await asyncio.sleep(0.02)
    return pred()


@pytest.mark.asyncio
async def test_handoff_task_goal_appears_in_activity_with_caller(hub):
    client, gateway, tools, root = hub
    out = await tools["handoff_task"](to="jaeger", task="summarise the repo", thread="t-codex", id="g-codex",
                                      workspace_folder=str(root))
    assert out["kind"] == "goal"
    req = "agent-codex-g-codex"
    assert await _wait(lambda: (gateway.store.get_request(req) or {}).get("status") == "completed", gateway)

    items = [i for i in await _activity(client) if (i["refs"] or {}).get("goal_id") == "g-codex"]
    by_kind = {i["kind"]: i for i in items}
    assert {"turn.start", "turn.finish"} <= set(by_kind)
    for i in items:
        assert i["refs"]["caller_id"] == "codex" and i["refs"]["caller_kind"] == "mcp"
        assert i["refs"]["thread"] == "t-codex" and i["refs"]["session_id"].startswith("codex:")
        assert i["actor_id"] == "codex" and i["agent_id"] == "native:jaeger"
    assert by_kind["turn.start"]["data"]["caller"]["status"] == "running"
    assert by_kind["turn.finish"]["data"]["caller"]["status"] == "completed"
    assert "codex (mcp) goal g-codex completed" in by_kind["turn.finish"]["summary"]
    assert len(items) == len({(i["kind"], i["refs"]["goal_id"]) for i in items})  # one row per transition

    # event_id is the real stream id (same rule as the global stream: G1)
    with gateway.store._immediate() as conn:
        ev = {r[0]: r[1] for r in conn.execute("SELECT event_id, event FROM events WHERE session_id=?",
                                               (by_kind["turn.start"]["refs"]["session_id"],))}
    assert ev[by_kind["turn.start"]["event_id"]] == "turn.start"
    # filter by caller via agent_id (matches actor_id)
    assert {i["refs"].get("goal_id") for i in await _activity(client, agent_id="codex")} == {"g-codex"}


@pytest.mark.asyncio
async def test_owner_chat_turns_stay_out_of_activity(hub):
    client, gateway, tools, root = hub
    gateway.store.ensure_session("web-1", metadata={"agent_id": "native:jaeger"})
    with gateway.store._immediate() as conn:
        agent_activity.ensure(conn)
        agent_activity.record(conn, 999_001, "web-1", "turn.start", {"request_id": "r1", "text": "hi"}, 1.0)
        agent_activity.record(conn, 999_002, "codex:bridge-x", "turn.start", {"request_id": "r2", "text": "x"}, 1.0)
    kinds = {(i["session_id"], i["kind"]) for i in await _activity(client)}
    assert ("web-1", "turn.start") not in kinds and ("codex:bridge-x", "turn.start") in kinds


def test_caller_of():
    assert agent_activity.caller_of("codex:bridge-t") == ("codex", "mcp")
    assert agent_activity.caller_of("a2a:x") == ("a2a", "a2a")
    assert agent_activity.caller_of("agent:ares:bridge-t") == ("ares", "mcp")
    assert agent_activity.caller_of("web-123") is None and agent_activity.caller_of("agent:nobody:x") is None
