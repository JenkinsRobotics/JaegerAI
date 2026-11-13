"""Collaboration mode: one mind (inner helpers via ``delegate``), team, auto."""
from __future__ import annotations

import asyncio

import pytest
from types import SimpleNamespace
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.contract.trace import classify
from jaeger_ai.core.runtime import collaboration as collab


def test_mode_defaults_to_one_mind_and_unreadable_never_widens(tmp_path):
    assert collab.configured_mode(None) == "one_mind"
    cfg = tmp_path / "config.yaml"
    assert collab.configured_mode(cfg) == "one_mind"  # absent file
    cfg.write_text("automation:\n  collaboration_mode: team\n")
    assert collab.configured_mode(cfg) == "team"
    cfg.write_text("automation:\n  collaboration_mode: chaos\n")
    assert collab.configured_mode(cfg) == "one_mind"
    cfg.write_text(": : not yaml [")
    assert collab.configured_mode(cfg) == "one_mind"


def test_helper_tools_are_the_leads_minus_messaging_memory_schedule_and_delegation():
    lead = ["read_file", "search_files", "web_search", "memory", "remember", "send_message", "send_email",
            "schedule_prompt", "call_agent", "delegate", "run_team", "clarify", "set_autonomy", "agent_notes",
            "notify", "create_event", "terminal"]
    assert collab.helper_tool_grant(lead) == ["read_file", "search_files", "terminal", "web_search"]


def test_call_agent_alias_follows_the_mode():
    assert collab.call_agent_is_delegate("one_mind", explicit_mention=True) is True
    assert collab.call_agent_is_delegate("team", explicit_mention=False) is False
    assert collab.call_agent_is_delegate("auto", explicit_mention=False) is True
    assert collab.call_agent_is_delegate("auto", explicit_mention=True) is False


def test_helper_prompt_is_one_mind_and_memory_is_read_only():
    text = collab.helper_prompt(display_name="Design & Style", specialty="design", brief="Review the header",
                                memory_excerpt="- favorite_color = blue", tools=["read_file"])
    assert "inner helper" in text and "never address the person" in text and "Review the header" in text
    assert "read-only" in text and "favorite_color" in text and "read_file" in text
    assert "token" not in collab.scrub_excerpt("- github_token = abc\n- color = blue")


def test_trace_draws_a_helper_node_under_the_asking_tool_call():
    started = classify("delegate.started", {"request_id": "req-1", "handoff_id": "handoff_9", "call_id": "call_3",
                                            "agent_name": "Design & Style"})
    assert started["kind"] == "subagent" and started["span_id"] == "agent:handoff_9"
    assert started["parent_span_id"] == "tool:tool_req1_call_3" and started["state"] == "running"
    done = classify("delegate.finished", {"request_id": "req-1", "handoff_id": "handoff_9",
                                          "call_id": "tool_req1_call_3"})
    assert done["state"] == "succeeded" and done["parent_span_id"] == "tool:tool_req1_call_3"
    failed = classify("delegate.failed", {"request_id": "req-1", "handoff_id": "handoff_9", "status": "cancelled"})
    assert failed["state"] == "cancelled" and failed["parent_span_id"] == "run:req-1"


@pytest_asyncio.fixture
async def collab_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "home"))
    from jaeger_ai.core.agent_registry import AgentRegistry
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRole
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    reg = AgentRegistry(tmp_path / "home")
    if reg.get_agent("native:jaeger") is None:
        reg.create_agent("jaeger", kind=AgentKind.NATIVE, role=AgentRole.LEAD, display_name="Jaeger",
                         metadata={}, scaffold_instance=False)
    reg.create_agent("ds", kind=AgentKind.NATIVE, role=AgentRole.SPECIALIST, display_name="Jaeger Design & Style",
                     metadata={"team": "pilot", "specialist": True, "summary": "design"}, scaffold_instance=False)
    reg.create_agent("eng", kind=AgentKind.NATIVE, role=AgentRole.SPECIALIST, display_name="Engineer",
                     metadata={"team": "pilot", "specialist": True, "summary": "eng"}, scaffold_instance=False)
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
    gateway.app.on_startup.clear()
    monkeypatch.setattr(gateway, "_registry", lambda: AgentRegistry(tmp_path / "home"))
    from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml
    cfg = tmp_path / "config.yaml"
    dump_yaml(cfg, Config(instance_name="collab-test", model=ModelConfig(model_path="/dev/null")))
    monkeypatch.setattr(gateway, "_config_path", lambda: cfg)
    calls = []
    gate: dict[str, asyncio.Event | None] = {"hold": None}

    async def fake_specialist_chat(session_id, text, *, request_id, agent_id=None, allowed_tools=None, **_):
        calls.append({"agent_id": agent_id, "session_id": session_id, "text": text, "tools": allowed_tools})
        gateway.event_bus.publish(session_id, "model.finished", {"usage": {"prompt_tokens": 120, "completion_tokens": 30}})
        if gate["hold"] is not None:
            await gate["hold"].wait()
        return "Header hierarchy is fine; tighten the gap to 8px.", "test:model"

    monkeypatch.setattr(gateway, "_specialist_chat", fake_specialist_chat)
    async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as c:
        yield c, gateway, calls, cfg, gate


async def _origin(gateway, text="Review the header please"):
    sid = "chat-collab-1"
    gateway.store.ensure_session(sid, title="chat", profile="jaeger", metadata={"agent_id": "native:jaeger"})
    from jaeger_ai.core.gateway.caller_auth import CALLERS
    # The turn's caller is the WebUI actor, so the helper is a qualified child of it.
    row = gateway.store.admit_request(sid, text, request_id="req-collab-1",
                                      requested={"caller": CALLERS["webui"].actor})
    return sid, row["request_id"]


async def _settle(gateway, handoff_id):
    for _ in range(200):
        rec = gateway.store.get_handoff(handoff_id)
        if rec and rec["status"] in {"completed", "failed", "cancelled", "execution_unknown"}:
            return rec
        await asyncio.sleep(0.02)
    return gateway.store.get_handoff(handoff_id)


@pytest.mark.asyncio
async def test_collaboration_setting_round_trips_through_the_gateway(collab_client):
    client, gateway, _, cfg, _ = collab_client
    got = await (await client.get("/v1/runtime/collaboration")).json()
    assert got["mode"] == "one_mind" and [o["id"] for o in got["options"]] == ["one_mind", "team", "auto"]
    resp = await client.post("/v1/runtime/collaboration", json={"mode": "team"})
    assert resp.status == 200 and (await resp.json())["mode"] == "team"
    assert "collaboration_mode: team" in cfg.read_text()
    assert (await (await client.get("/v1/team/mode")).json())["mode"] == "team"
    assert (await client.post("/v1/runtime/collaboration", json={"mode": "crew"})).status == 400


@pytest.mark.asyncio
async def test_one_mind_delegate_runs_an_inner_helper_and_returns_only_to_the_lead(collab_client):
    client, gateway, calls, _, _ = collab_client
    sid, rid = await _origin(gateway)
    resp = await client.post("/v1/agents/native:ds/handoff", json={
        "task": "Review the header hierarchy", "mode": "delegate", "session_id": sid, "parent_run_id": rid,
        "call_id": "call_abc", "require_approval": True, "context": "Header is 48px tall",
        "lead_allowed_tools": ["read_file", "search_files", "memory", "send_message", "call_agent", "schedule_prompt"]})
    assert resp.status == 200, await resp.text()
    record = await resp.json()
    meta = record["metadata"]
    assert record["status"] == "admitted" and record["require_approval"] is False
    assert meta["collaboration"] == "delegate" and meta["call_id"] == "tool_reqcollab1_call_abc"
    assert sorted(meta["allowed_tools"]) == ["read_file", "search_files"]
    done = await _settle(gateway, record["id"])
    assert done["status"] == "completed"
    assert done["result"]["metadata"]["tokens"]["total"] == 150
    prompt = calls[0]["text"]
    assert "inner helper" in prompt and "Header is 48px tall" in prompt and "never address the person" in prompt
    assert set(calls[0]["tools"]) <= {"read_file", "search_files"}
    events = gateway.store.replay_events(sid, 0, session_only=True)["events"]
    names = [e["event"] for e in events]
    assert "delegate.started" in names and "delegate.finished" in names
    assert not any(n.startswith("agent.handoff") or n == "agent.message" for n in names)  # one voice
    fin = next(e for e in events if e["event"] == "delegate.finished")
    trace = fin.get("trace") or fin["data"].get("trace")
    assert trace["kind"] == "subagent" and trace["state"] == "succeeded"
    assert trace["parent_span_id"] == "tool:tool_reqcollab1_call_abc"
    assert fin["data"]["tokens"]["total"] == 150 and "8px" in fin["data"]["summary"]
    kinds = [m.get("kind") for m in gateway.store.list_messages(sid, limit=50)["messages"]]
    assert "handoff_result" not in kinds and "handoff_request" not in kinds
    team = await (await client.get("/v1/team")).json()
    assert team["mode"] == "one_mind"
    row = next(h for h in team["handoffs"] if h["id"] == record["id"])
    assert row["kind"] == "delegate" and row["tokens"]["total"] == 150


@pytest.mark.asyncio
async def test_helpers_cannot_delegate_further(collab_client):
    client, gateway, _, _, _ = collab_client
    gateway.store.ensure_session("helper-child", title="h", profile="jaeger",
                                 metadata={"agent_id": "native:ds", "handoff_child": True})
    resp = await client.post("/v1/agents/native:eng/handoff", json={
        "task": "go deeper", "mode": "delegate", "session_id": "helper-child"})
    assert resp.status == 409 and "cannot delegate further" in (await resp.json())["error"]


@pytest.mark.asyncio
async def test_concurrency_cap_and_stop_cancels_the_helper(collab_client):
    client, gateway, calls, _, gate = collab_client
    gate["hold"] = asyncio.Event()
    sid, rid = await _origin(gateway)
    ids = []
    for i in range(collab.MAX_CONCURRENT):
        r = await client.post("/v1/agents/native:ds/handoff", json={
            "task": f"brief {i}", "mode": "delegate", "session_id": sid, "parent_run_id": rid,
            "lead_allowed_tools": ["read_file"]})
        assert r.status == 200, await r.text()
        ids.append((await r.json())["id"])
    over = await client.post("/v1/agents/native:ds/handoff", json={
        "task": "one too many", "mode": "delegate", "session_id": sid, "parent_run_id": rid})
    assert over.status == 409 and "at once" in (await over.json())["error"]
    for _ in range(100):
        if len(calls) >= collab.MAX_CONCURRENT:
            break
        await asyncio.sleep(0.02)
    stop = await client.post(f"/v1/sessions/{sid}/cancel", json={"request_id": rid})
    assert stop.status == 200, await stop.text()
    assert len((await stop.json())["owned_handoff_cancellations"]) == collab.MAX_CONCURRENT
    gate["hold"].set()
    states = {(await _settle(gateway, h))["status"] for h in ids}
    assert states <= {"cancelled", "execution_unknown", "failed"}, states


@pytest.mark.asyncio
async def test_call_agent_is_a_delegate_in_one_mind_and_a_handoff_in_team(collab_client, monkeypatch):
    client, gateway, _, _, _ = collab_client
    sid, rid = await _origin(gateway, "@Jaeger Design & Style please review")
    body = {"task": "review", "via": "call_agent", "session_id": sid, "parent_run_id": rid, "require_approval": False}
    one = await (await client.post("/v1/agents/native:ds/handoff", json=body)).json()
    assert one["metadata"]["collaboration"] == "delegate"
    await _settle(gateway, one["id"])
    monkeypatch.setattr(gateway, "_collaboration_mode", lambda: "auto")
    auto = await (await client.post("/v1/agents/native:ds/handoff", json=body)).json()
    assert auto["metadata"]["collaboration"] == "handoff"  # explicit @mention keeps the team hand-off
    await _settle(gateway, auto["id"])
    monkeypatch.setattr(gateway, "_collaboration_mode", lambda: "team")
    team = await (await client.post("/v1/agents/native:eng/handoff", json=body)).json()
    assert team["metadata"]["collaboration"] == "handoff"
    await _settle(gateway, team["id"])


@pytest.mark.asyncio
async def test_one_mind_turns_rooms_off_and_routes_chats_to_jaeger(collab_client, monkeypatch):
    client, gateway, _, _, _ = collab_client
    resp = await client.post("/v1/team/rooms", json={"title": "R", "members": ["native:ds", "native:eng"]})
    assert resp.status == 409 and "One mind" in (await resp.json())["error"]
    created = await (await client.post("/v1/sessions", json={"agent_id": "native:ds", "title": "x"})).json()
    assert created["metadata"]["agent_id"] == "native:jaeger"
    assert created["metadata"]["requested_agent_id"] == "native:ds"
    session = {"session_id": "s", "metadata": {"agent_id": "native:ds"}}
    ds = gateway._registry().get_agent("native:ds")
    assert gateway._one_mind_front_door(session, "native:ds", ds)[0] == "native:jaeger"
    assert gateway._one_mind_front_door({"metadata": {"handoff_child": True}}, "native:ds", ds) is None
    # A built-in specialist the owner switched to explicitly keeps the owner's choice.
    builtin = SimpleNamespace(id="native:gateway", metadata={})
    assert gateway._one_mind_front_door(session, "native:gateway", builtin) is None
    monkeypatch.setattr(gateway, "_collaboration_mode", lambda: "team")
    assert gateway._one_mind_front_door(session, "native:ds", ds) is None
    ok = await client.post("/v1/team/rooms", json={"title": "R", "members": ["native:ds", "native:eng"]})
    assert ok.status == 201
