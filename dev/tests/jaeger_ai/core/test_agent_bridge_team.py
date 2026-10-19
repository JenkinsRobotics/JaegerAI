"""Real team HTTP handoff and native file effects in ephemeral bridge state."""

import asyncio
import importlib
import json

import pytest

from dev.tests.jaeger_ai.core import test_agent_bridge_tool_goals as fixture_source
from dev.tests.jaeger_ai.core.test_agent_bridge_tool_goals import (
    h,
    start,
    wait_for,
)
from jaeger_ai.features.agent_bridge.delegation import origin
from jaeger_ai.features.agent_bridge.tool_scope import confined_arguments, goal_scope

tool_bridge = fixture_source.tool_bridge


async def team_transport(client, app, monkeypatch):
    from jaeger_agent.task_port import task_scope

    module = importlib.import_module("jaeger_agent.tools.call_agent")
    monkeypatch.setenv("JAEGER_GATEWAY_URL", str(client.make_url("/")).rstrip("/"))
    monkeypatch.setattr(module, "_GATEWAY_AUTH", lambda: h("jaegerd"))
    monkeypatch.setattr(module, "APPROVAL_POLL_S", 0.01)
    original = app._execute_turn_inner
    app.team_executions = []

    async def dispatch(session_id, turn_id, text, *, request_id=None, execution=None):
        if session_id.startswith("specialist:"):
            session = app.store.get_session(session_id)
            handoff = app.store.get_handoff(session["metadata"]["handoff_id"])
            text = handoff["task"]
            standing = app._specialist_scope(
                app._resolve_session_agent(session_id), execution
            )
            if standing is not None:
                execution = standing["execution"]
            app.team_executions.append((session_id, request_id, execution))
        with task_scope(
            app.task_owner,
            session_id=session_id,
            request_id=request_id,
            execution=execution,
            user_text=text,
            source="user",
        ):
            await original(
                session_id, turn_id, text, request_id=request_id, execution=execution
            )

    monkeypatch.setattr(app, "_execute_turn_inner", dispatch)


async def owner_approve(client, app, kind=None):
    await wait_for(lambda: bool(app.store.list_pending_approvals()))
    approvals = app.store.list_pending_approvals()
    approval = next((a for a in approvals if kind is None or a["kind"] == kind), None)
    assert approval is not None, approvals
    aid = approval["approval_id"]
    for caller in ("ares", "grokbot"):
        assert (
            await client.post(
                f"/v1/approvals/{aid}", headers=h(caller), json={"decision": "once"}
            )
        ).status == 403
    assert (
        await client.post(
            f"/v1/approvals/{aid}", headers=h("cli"), json={"decision": "once"}
        )
    ).status == 200


@pytest.mark.asyncio
async def test_real_gateway_team_preserves_actor_workspace_and_owner_approvals(
    tool_bridge, monkeypatch
):
    client, app, root = tool_bridge
    await team_transport(client, app, monkeypatch)
    task = json.dumps(
        ["write_file", {"path": "team-proof.txt", "content": "real team child"}]
    )
    await start(
        client,
        root,
        name="call_agent",
        arguments={"agent_id": "native:builder", "task": task},
        id="team",
    )
    target = root / "team-proof.txt"
    await wait_for(lambda: bool(app.store.list_handoffs()))
    handoff = app.store.list_handoffs()[0]
    assert handoff["status"] == "pending_approval"
    assert handoff["metadata"]["caller_actor"] == "mcp:ares"
    assert not target.exists()
    await owner_approve(client, app, "handoff")
    await wait_for(lambda: bool(app.team_executions))
    assert app.team_executions[0][2]["caller"] == "mcp:ares"
    assert app.team_executions[0][2]["workspace"] == str(root)
    assert not target.exists()
    await owner_approve(client, app)
    await wait_for(lambda: target.exists())
    assert target.read_text() == "real team child"
    await wait_for(
        lambda: app.store.get_handoff(handoff["id"])["status"] == "completed"
    )
    await wait_for(
        lambda: app.store.get_request("agent-ares-team")["status"] == "completed"
    )
    sid, rid, execution = app.team_executions[0]
    binding = origin(app, sid, rid)
    assert binding == {
        "caller": "ares",
        "session": "ares:bridge-work",
        "request_id": "agent-ares-team",
    }
    from jaeger_os.core.tools.tool_registry import get_tool

    with goal_scope(app, sid, rid, execution):
        with pytest.raises(PermissionError):
            confined_arguments(
                get_tool("write_file"),
                {"path": str(root.parent / "foreign.txt"), "content": "escape"},
            )
        with pytest.raises(PermissionError):
            confined_arguments(
                get_tool("get_agent_result"), {"handoff_id": "handoff_foreign"}
            )
    assert not (root.parent / "foreign.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["handoff", "write"])
async def test_goal_cancel_denies_pending_team_and_child_writes(
    tool_bridge, monkeypatch, stage
):
    client, app, root = tool_bridge
    await team_transport(client, app, monkeypatch)
    task = json.dumps(
        ["write_file", {"path": "cancelled-team.txt", "content": "must not write"}]
    )
    await start(
        client,
        root,
        name="call_agent",
        arguments={"agent_id": "native:builder", "task": task},
        id="team-cancel",
    )
    await wait_for(lambda: bool(app.store.list_handoffs()))
    handoff = app.store.list_handoffs()[0]
    if stage == "write":
        await owner_approve(client, app, "handoff")
        await wait_for(
            lambda: (
                bool(app.team_executions) and bool(app.store.list_pending_approvals())
            )
        )
    assert (
        await client.post("/v1/agent-goals/team-cancel/cancel", headers=h(), json={})
    ).status == 200
    assert app.store.get_handoff(handoff["id"])["status"] == "cancelled"
    await asyncio.sleep(0.2)
    assert not (root / "cancelled-team.txt").exists()
    assert not app.store.list_pending_approvals()


@pytest.mark.asyncio
async def test_relay_cannot_spoof_parent_or_workspace_and_direct_callers_cannot_delegate(
    tool_bridge, monkeypatch
):
    client, app, root = tool_bridge
    await start(
        client, root, name="read_file", arguments={"path": "missing"}, id="parent"
    )
    await wait_for(
        lambda: app.store.get_request("agent-ares-parent")["status"] == "completed"
    )
    body = {
        "task": "inert",
        "session_id": "ares:bridge-work",
        "parent_run_id": "agent-ares-parent",
        "workspace": str(root),
        "require_approval": True,
        "request_id": "fixture-handoff",
    }
    endpoint = "/v1/agents/native:builder/handoff"
    assert (await client.post(endpoint, headers=h(), json=body)).status == 403
    headers = {**h("jaegerd"), "X-Jaeger-Actor": "mcp:grokbot"}
    assert (await client.post(endpoint, headers=headers, json=body)).status == 403
    headers = {**h("jaegerd"), "X-Jaeger-Actor": "mcp:ares"}
    assert (
        await client.post(
            endpoint, headers=headers, json={**body, "workspace": str(root.parent)}
        )
    ).status == 403
    assert (
        await client.post(
            endpoint, headers=headers, json={**body, "parent_run_id": "foreign"}
        )
    ).status == 403
    assert app.store.list_handoffs() == []


@pytest.mark.asyncio
async def test_run_team_uses_canonical_children_and_each_handoff_approval(
    tool_bridge, monkeypatch
):
    client, app, root = tool_bridge
    await team_transport(client, app, monkeypatch)
    (root / "input.txt").write_text("own workspace only")
    task = json.dumps(["read_file", {"path": "input.txt"}])
    assignments = json.dumps(
        [
            {"agent_id": "native:builder", "task": task},
            {"agent_id": "native:reviewer", "task": task},
        ]
    )
    await start(
        client,
        root,
        name="run_team",
        arguments={"assignments": assignments},
        id="team-fanout",
    )
    await wait_for(lambda: len(app.store.list_handoffs()) == 2)
    assert all(row["status"] == "pending_approval" for row in app.store.list_handoffs())
    await owner_approve(client, app, "handoff")
    await owner_approve(client, app, "handoff")
    await wait_for(
        lambda: app.store.get_request("agent-ares-team-fanout")["status"] == "completed"
    )
    assert len(app.team_executions) == 2
    assert all(row["status"] == "completed" for row in app.store.list_handoffs())
    assert all(
        execution["caller"] == "mcp:ares" for _, _, execution in app.team_executions
    )
    results = [json.loads(message["content"]) for message in app.fixture_calls]
    assert any(
        result.get("ok") and len(result.get("results", [])) == 2 for result in results
    )


@pytest.mark.asyncio
async def test_handoff_retry_cannot_cross_goal_and_fake_child_metadata_is_not_a_binding(
    tool_bridge,
):
    from jaeger_ai.features.agent_bridge.delegation import child_request_id

    client, app, root = tool_bridge
    for goal_id in ("parent-one", "parent-two"):
        await start(
            client, root, name="read_file", arguments={"path": "missing"}, id=goal_id
        )
        await wait_for(
            lambda goal_id=goal_id: (
                app.store.get_request("agent-ares-" + goal_id)["status"] == "completed"
            )
        )
    headers = {**h("jaegerd"), "X-Jaeger-Actor": "mcp:ares"}
    body = {
        "task": "inert",
        "session_id": "ares:bridge-work",
        "parent_run_id": "agent-ares-parent-one",
        "workspace": str(root),
        "require_approval": False,
        "request_id": "same-delivery",
    }
    endpoint = "/v1/agents/native:builder/handoff"
    response = await client.post(endpoint, headers=headers, json=body)
    assert response.status == 202
    handoff = await response.json()
    assert handoff["status"] == "pending_approval"  # caller cannot waive the card
    assert (await client.post(endpoint, headers=headers, json=body)).status == 200
    response = await client.post(
        endpoint,
        headers=headers,
        json={**body, "parent_run_id": "agent-ares-parent-two"},
    )
    assert response.status == 409
    app.store.ensure_session(
        "ares:forged-child", metadata={"handoff_id": handoff["id"]}
    )
    with pytest.raises(PermissionError):
        origin(app, "ares:forged-child", child_request_id(handoff["request_id"]))
    from jaeger_os.core.tools.tool_registry import get_tool

    parent = app.store.get_request("agent-ares-parent-two")
    with (
        goal_scope(
            app, parent["session_id"], parent["request_id"], parent["execution"]
        ),
        pytest.raises(PermissionError),
    ):
        confined_arguments(get_tool("get_agent_result"), {"handoff_id": handoff["id"]})


@pytest.mark.asyncio
async def test_catalog_upgrade_retry_retains_original_admitted_grant(
    tool_bridge, monkeypatch
):
    from jaeger_ai.features.agent_bridge import routes

    client, app, root = tool_bridge
    await start(
        client, root, name="read_file", arguments={"path": "missing"}, id="retry"
    )
    await wait_for(
        lambda: app.store.get_request("agent-ares-retry")["status"] == "completed"
    )
    before = app.store.get_request("agent-ares-retry")
    monkeypatch.setattr(routes, "supported_tools", lambda: ["new-ungranted-tool"])
    await start(
        client, root, name="read_file", arguments={"path": "missing"}, id="retry"
    )
    after = app.store.get_request("agent-ares-retry")
    assert before["execution"] == after["execution"]
    assert "new-ungranted-tool" not in after["execution"]["allowed_tools"]
