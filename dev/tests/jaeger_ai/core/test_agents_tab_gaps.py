"""Agents tab gaps G1-G6 (shapes: /workspace/jaeger-agents-tab-api-shapes.md). Temp stores only."""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.fixture(autouse=True)
def _secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_SECRETS_DIR", str(tmp_path / "secrets"))


def gw(tmp_path):
    g = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    g.store.ensure_session("chat1", metadata={"agent_id": "native:jaeger"})
    return g


def H(hid, status="running", **kw):
    return {"id": hid, "from_agent_id": "native:jaeger", "to_agent_id": "specialist:coder", "task": "Fix login",
            "status": status, "result": {}, "metadata": {}, **kw}


# ── G1 ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_g1_activity_ids_equal_global_stream_ids_and_dedupe(tmp_path):
    g = gw(tmp_path)
    glob = g.event_bus.publish("*", "agent.handoff", {"handoff": H("h1")})
    g.event_bus.publish("chat1", "agent.handoff", {"handoff": H("h1"), "request_id": "r1"})
    # origin copy first, then global: the global id still wins
    g.event_bus.publish("chat1", "agent.handoff.finished", {"handoff": H("h1", "completed"), "request_id": "r1"})
    glob2 = g.event_bus.publish("*", "agent.handoff.finished", {"handoff": H("h1", "completed")})
    g._publish_approval_request("chat1", None, {"approval_id": "ap1", "prompt": "Run rm?"})
    g.store.create_approval(kind="x", prompt="p", options=["once", "deny"], approval_id="ap1", session_id="chat1")
    g.event_bus.publish("*", "project.checked", {"project_id": "p1", "result": {"ok": True}})
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        out = await (await c.get("/v1/activity")).json()
        kinds = [i["kind"] for i in out["items"]]
        assert kinds == ["project.checked", "approval.request", "agent.handoff.finished", "agent.handoff"]
        by = {i["kind"]: i for i in out["items"]}
        assert by["agent.handoff"]["event_id"] == glob.event_id and by["agent.handoff"]["session_id"] == "*"
        assert by["agent.handoff.finished"]["event_id"] == glob2.event_id
        assert by["agent.handoff"]["agent_id"] == "specialist:coder" and by["agent.handoff"]["actor_id"] == "native:jaeger"
        ap = by["approval.request"]
        assert ap["data"]["agent_id"] == "native:jaeger" and ap["agent_id"] == "native:jaeger" and ap["needs_me"]
        assert by["project.checked"]["summary"] == "project p1 check passed" and by["project.checked"]["refs"]["project_id"] == "p1"
        page = await (await c.get("/v1/activity?limit=2")).json()
        assert len(page["items"]) == 2 and page["has_more"] and page["next_before"] == page["items"][-1]["event_id"]
        rest = await (await c.get(f"/v1/activity?limit=5&before={page['next_before']}")).json()
        assert [i["kind"] for i in rest["items"]] == kinds[2:] and not rest["has_more"]
        assert [i["kind"] for i in (await (await c.get("/v1/activity?kind=agent.handoff*")).json())["items"]] == kinds[2:]
        assert [i["approval_id"] if False else i["kind"] for i in (await (await c.get("/v1/activity?needs_me=1")).json())["items"]] == ["approval.request"]
        assert [i["kind"] for i in (await (await c.get("/v1/activity?agent_id=specialist:coder")).json())["items"]] == kinds[2:]
        assert (await c.get("/v1/activity?before=abc")).status == 400
        assert (await c.get("/v1/activity?limit=999")).status == 400
    reopened = GatewaySessionStore(g.store.path)
    assert len(reopened.agent_activity()["items"]) == 4  # durable


def test_g1_backfill_from_existing_events(tmp_path):
    from jaeger_ai.core.gateway import agent_activity
    s = GatewaySessionStore(tmp_path / "g.sqlite3")
    with s._immediate() as conn:
        conn.execute("DROP TABLE IF EXISTS agent_activity")
    agent_activity._ready.clear()
    s.append_event("*", "agent.handoff", {"handoff": H("h9")})
    assert s.agent_activity()["items"][0]["refs"]["handoff_id"] == "h9"
