"""/v1/tasks carries agent_id/eta/runner; /v1/agents/summary derives status (D2).

No agent_status table and no /v1/agent-status route: the board's data is the
existing durable task projection plus handoffs and direct-chat sessions.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.agent_summary import agent_status, summarize_agents
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.models import DurableTask


def test_task_round_trips_board_fields_and_defaults_old_rows():
    task = DurableTask("t1", "native:jaeger", "goal", agent_id="native:gateway",
                       eta="2026-10-17T14:30:00-07:00", runner="delegate:native:gateway")
    data = task.to_dict()
    assert (data["agent_id"], data["eta"], data["runner"]) == (
        "native:gateway", "2026-10-17T14:30:00-07:00", "delegate:native:gateway")
    assert DurableTask.from_dict(data).to_dict() == data
    legacy = {k: v for k, v in data.items() if k not in {"agent_id", "eta", "runner"}}
    old = DurableTask.from_dict(legacy).to_dict()
    assert (old["agent_id"], old["eta"], old["runner"]) == ("native:jaeger", None, "native")


@pytest.mark.parametrize("handoff,tasks,expected", [
    (None, [], "idle"),
    ({"status": "running"}, [], "working"),
    ({"status": "pending_approval"}, [{"state": "running"}], "waiting_approval"),
    ({"status": "completed"}, [{"state": "blocked"}], "blocked"),
    ({"status": "execution_unknown"}, [], "error"),
    (None, [{"state": "queued"}], "working"),
])
def test_agent_status(handoff, tasks, expected):
    assert agent_status(handoff, tasks) == expected


def test_summary_rows_preview_and_order():
    agents = [{"id": "native:jaeger", "display_name": "Jaeger", "role": "lead"},
              {"id": "native:gateway", "display_name": "Gateway", "role": "specialist"},
              {"id": "native:surfaces", "display_name": "Surfaces", "role": "specialist"}]
    out = summarize_agents(
        agents,
        tasks=[{"task_id": "t1", "agent_id": "native:gateway", "goal": "port move", "state": "running",
                "eta": "2026-10-17T14:30:00-07:00", "runner": "native", "updated_at": 10}],
        handoffs=[{"id": "h1", "to_agent_id": "native:surfaces", "status": "completed",
                   "task": "x", "result": {"summary": "all " * 60}, "updated_at": 20}],
        sessions=[{"session_id": "chat-g", "agent_id": "native:gateway", "updated_at": 30, "title": "t"}],
        last_message=lambda sid: "latest direct message",
    )
    rows = {r["id"]: r for r in out["agents"]}
    assert [r["id"] for r in out["agents"]] == ["native:jaeger", "native:gateway", "native:surfaces"]
    g = rows["native:gateway"]
    assert g["status"] == "working" and g["session_id"] == "chat-g"
    assert g["last_preview"] == "latest direct message" and g["last_activity_at"] == 30
    assert g["task"]["eta"] == "2026-10-17T14:30:00-07:00"
    s = rows["native:surfaces"]
    assert s["status"] == "idle" and s["last_handoff_id"] == "h1" and len(s["last_preview"]) <= 140
    assert rows["native:jaeger"]["status"] == "idle" and rows["native:jaeger"]["last_preview"] == ""


@pytest_asyncio.fixture
async def gateway(tmp_path):
    gw = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "tasks.sqlite3"))
    gw.app.on_startup.clear()
    async with TestClient(TestServer(gw.app), headers=client_headers("webui")) as c:
        yield gw, c


@pytest.mark.asyncio
async def test_post_tasks_validates_and_stores_board_fields(gateway):
    gw, client = gateway
    gw.store.ensure_session("parent", title="p")
    specialist = next(a.id for a in gw._registry().list_agents() if a.role.value == "specialist")
    bad = [{"agent_id": "nope"}, {"eta": "tomorrow"}, {"eta": "2026-10-17T14:30:00"},
           {"runner": "remote"}, {"runner": "delegate:nope"}]
    for extra in bad:
        resp = await client.post("/v1/tasks", json={"session_id": "parent", "goal": f"g {extra}", **extra})
        assert resp.status == 400, extra
    resp = await client.post("/v1/tasks", json={
        "session_id": "parent", "goal": "board goal", "agent_id": specialist,
        "eta": "2026-10-17T14:30:00-07:00", "runner": f"delegate:{specialist}"})
    assert resp.status in {200, 201}, await resp.text()
    tid = (await resp.json())["task_id"]
    task = await (await client.get(f"/v1/tasks/{tid}")).json()
    assert (task["agent_id"], task["runner"]) == (specialist, f"delegate:{specialist}")
    listed = await (await client.get(f"/v1/tasks?agent_id={specialist}")).json()
    assert [t["task_id"] for t in listed["tasks"]] == [tid]
    summary = await (await client.get("/v1/agents/summary")).json()
    row = next(r for r in summary["agents"] if r["id"] == specialist)
    assert row["task"]["task_id"] == tid
    assert summary["agents"][0]["role"] == "lead"


@pytest.mark.asyncio
async def test_summary_route_is_not_shadowed_and_needs_token(gateway):
    gw, client = gateway
    assert (await client.get("/v1/agents/summary")).status == 200
    anon_gw = JaegerGatewayApp(store=gw.store)
    anon_gw.app.on_startup.clear()
    async with TestClient(TestServer(anon_gw.app)) as anon:
        assert (await anon.get("/v1/agents/summary")).status == 401
        assert (await anon.get("/v1/agents/summary", headers=client_headers("mcp"))).status == 403


def test_summary_marks_unseen_until_seen():
    agents = [{"id": "native:gateway", "display_name": "Gateway", "role": "specialist"}]
    sessions = [{"session_id": "s1", "agent_id": "native:gateway", "updated_at": 100.0,
                 "last_message_preview": "hi"}]
    row = summarize_agents(agents, tasks=[], handoffs=[], sessions=sessions)["agents"][0]
    assert row["unseen"] is True and row["seen_at"] is None
    row = summarize_agents(agents, tasks=[], handoffs=[], sessions=sessions,
                           seen={"native:gateway": {"seen_at": 150.0}})["agents"][0]
    assert row["unseen"] is False and row["seen_at"] == 150.0


@pytest.mark.asyncio
async def test_agent_seen_route_persists_and_validates(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    agent_id = gateway._registry().list_agents()[0].id
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        resp = await client.post(f"/v1/agents/{agent_id}/seen", json={"seen_at": 42, "event_id": 7})
        assert resp.status == 200
        assert (await resp.json()) == {"agent_id": agent_id, "seen_at": 42.0, "event_id": 7}
        assert gateway.store.agents_seen()[agent_id]["seen_at"] == 42.0
        assert (await client.post("/v1/agents/nope/seen", json={})).status == 404
        assert (await client.post(f"/v1/agents/{agent_id}/seen", json={"seen_at": "x"})).status == 400


def test_agent_record_disabled_comes_from_metadata():
    from jaeger_ai.core.agent_registry.registry import with_roster_flags
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRecord, AgentRole

    rec = AgentRecord(id="x", name="x", kind=AgentKind.NATIVE, display_name="X", source="registry",
                      role=AgentRole.SPECIALIST, metadata={"disabled": True})
    assert rec.disabled is True
    flags = with_roster_flags(rec)
    assert (flags["hidden"], flags["disabled"]) == (False, True)


@pytest.mark.asyncio
async def test_role_filter_carries_hidden_and_disabled_flags(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        body = await (await client.get("/v1/agents?role=specialist")).json()
    assert body["role"] == "specialist" and body["agents"]
    for agent in body["agents"]:
        assert isinstance(agent["hidden"], bool) and isinstance(agent["disabled"], bool)


@pytest.mark.asyncio
async def test_sessions_filter_by_agent_and_direct_chat_is_global(tmp_path):
    from jaeger_ai.core.gateway.event_bus import EVENT_TYPES

    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    agent_id = gateway._registry().list_agents(role="specialist")[0].id
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        for sid in ("a", "b"):
            assert (await client.post("/v1/sessions", json={"session_id": sid})).status in (200, 201)
        resp = await client.post("/v1/sessions/a/handoff", json={"to_agent_id": agent_id})
        assert resp.status == 200
        listed = (await (await client.get(f"/v1/sessions?agent_id={agent_id}")).json())["sessions"]
        assert [s["session_id"] for s in listed] == ["a"]
        assert len((await (await client.get("/v1/sessions")).json())["sessions"]) == 2
    events = gateway.store.replay_events("*", 0)["events"]
    direct = [e for e in events if e["event"] == "agent.direct_chat"]
    assert direct and direct[-1]["data"]["agent_id"] == agent_id and direct[-1]["data"]["session_id"] == "a"
    assert {"session.handoff", "agent.direct_chat"} <= EVENT_TYPES


@pytest.mark.asyncio
async def test_session_list_rows_carry_preview_activity_and_event_cursor(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    store = gateway.store
    store.ensure_session("specialist:gateway:1", title="Specialist chat")
    store.append_message("specialist:gateway:1", "user", "first")
    store.append_message("specialist:gateway:1", "assistant", "line one\n  line two " + "x" * 200)
    evt = gateway.event_bus.publish("specialist:gateway:1", "session.updated", {"session": {}})
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        resp = await client.get("/v1/sessions")
        assert resp.status == 200
        row = (await resp.json())["sessions"][0]
        # The WebUI (unprefixed caller) reads specialist: sessions.
        assert (await client.get("/v1/sessions/specialist:gateway:1")).status == 200
    assert row["session_id"] == "specialist:gateway:1"
    assert row["last_message_preview"].startswith("line one line two x")
    assert len(row["last_message_preview"]) == 140
    assert row["last_activity_at"] >= row["updated_at"]
    assert row["last_event_id"] == evt.event_id


@pytest.mark.asyncio
async def test_global_stream_replays_only_global_events_and_respects_scopes(tmp_path):
    import asyncio
    import json as _json

    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "s.db"))
    gateway.app.on_startup.clear()
    gateway.event_bus.publish("s1", "session.updated", {"session": {}})
    glob = gateway.event_bus.publish("*", "agent.created", {"agent": {"id": "x"}})
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
        resp = await client.get("/v1/events/stream")
        assert resp.status == 200 and resp.headers["Content-Type"].startswith("text/event-stream")
        chunk = await asyncio.wait_for(resp.content.readuntil(b"\n\n"), 5)
        resp.close()
        frame = chunk.decode()
        assert frame.startswith(f"id: {glob.event_id}\nevent: agent.created\n")
        assert _json.loads(frame.split("data: ", 1)[1])["session_id"] == "*"
        assert (await client.get("/v1/events/stream?last_event_id=x")).status == 400
    async with TestClient(TestServer(gateway.app), headers=client_headers("mcp")) as client:
        assert (await client.get("/v1/events/stream")).status in (401, 403)
    async with TestClient(TestServer(gateway.app)) as client:
        assert (await client.get("/v1/events/stream")).status == 401
