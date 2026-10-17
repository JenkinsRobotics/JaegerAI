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
