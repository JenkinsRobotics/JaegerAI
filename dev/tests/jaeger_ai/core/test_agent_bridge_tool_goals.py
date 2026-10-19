"""Real local REST admission, real cognitive loop/tool dispatch and owner cards.

Only the model transport is scripted; no provider or production credentials.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import (
    JaegerGatewayApp,
    _GatewayToolConfirmationProvider,
)
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.agent_bridge.outcomes import project_goal
from jaeger_ai.features.agent_bridge.tool_scope import supported_tools


class Scripted:
    name = "bridge-test-only"

    def __init__(self, name, args):
        self.script = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "fixture-call", "name": name, "arguments": args}],
            },
            {"role": "assistant", "content": "completed; verified!"},
        ]

    def format_messages(self, messages, tools, system):
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):
        return self.script.pop(0)

    def parse_response(self, raw):
        return raw

    def supports(self, feature):
        return False


@pytest_asyncio.fixture
async def tool_bridge(tmp_path, monkeypatch):
    from jaeger_agent.core import workspace

    from jaeger_ai.core.entity.authority import AuthorityLayer
    from jaeger_ai.core.entity.runtime import EntityRuntime
    from jaeger_ai.core.instance.instance import InstanceLayout

    instance = tmp_path / "instance"
    instance.mkdir()
    layout = InstanceLayout(root=instance)
    for path in (layout.logs_dir, layout.skills_dir, layout.workspace_dir):
        path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "granted"
    root.mkdir()
    # Scope only ephemeral layout; never bind or open a live runtime.
    monkeypatch.setattr(workspace, "_layout", layout)
    runtime = SimpleNamespace(
        layout=layout,
        authority_layer=AuthorityLayer(),
        event_store=SimpleNamespace(append=lambda *a, **k: None),
        record_tool_start=lambda *a, **k: None,
        record_tool_result=lambda *a, **k: None,
    )
    monkeypatch.setattr(
        EntityRuntime, "get_singleton", classmethod(lambda cls, *a, **k: runtime)
    )
    monkeypatch.setenv(
        "JAEGER_AGENT_WORKSPACES",
        json.dumps({"ares": [str(root)], "grokbot": [str(root)]}),
    )
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    app.app.on_startup.clear()
    app._schedule_summary = lambda *a: None
    app.fixture_calls = []

    async def model_transport(
        session_id, turn_id, text, *, request_id=None, execution=None
    ):
        from jaeger_agent import JaegerAgent, ProviderAdapter
        from jaeger_agent.tool_executor import tool_allowlist
        from jaeger_os.core.safety.permissions import PermissionPolicy, use_policy
        from jaeger_os.core.tools.tool_registry import get_tools

        name, arguments = json.loads(text)

        def run():
            workspace.set_project_root(execution["workspace"])
            adapter = Scripted(name, arguments)
            adapter.__class__ = type("FixtureAdapter", (Scripted, ProviderAdapter), {})
            with (
                tool_allowlist(execution["allowed_tools"]),
                use_policy(
                    PermissionPolicy(
                        confirmation=_GatewayToolConfirmationProvider(
                            app, session_id, request_id
                        )
                    )
                ),
            ):
                agent = JaegerAgent(
                    adapter,
                    tools=[
                        t for t in get_tools() if t.name in execution["allowed_tools"]
                    ],
                )
                agent.run_turn("Perform the requested file operation")
                app.fixture_calls.extend(
                    m for m in agent.messages if m.get("role") == "tool"
                )
            return "model claim of completed work"

        output = await asyncio.to_thread(run)
        cancelled = app._cancellations.is_cancelled(request_id)
        app.store.complete_request(
            request_id,
            status="cancelled" if cancelled else "completed",
            result={"output": output},
        )

    app._execute_turn_inner = model_transport
    async with TestClient(TestServer(app.app)) as client:
        app._loop = asyncio.get_running_loop()
        yield client, app, root
    for task in list(app._running_tasks.values()):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def h(caller="ares"):
    return caller_auth.client_headers(caller)


async def start(client, root, name="write_file", arguments=None, id="write1"):
    await client.post(
        "/v1/agent-messages",
        headers=h(),
        json={
            "id": "task-message",
            "thread": "work",
            "to": "jaegerd",
            "kind": "task",
            "title": "Write",
            "body": "fixture",
        },
    )
    response = await client.post(
        "/v1/agent-goals",
        headers=h(),
        json={
            "id": id,
            "thread": "work",
            "goal": json.dumps(
                [name, arguments or {"path": "proof.txt", "content": "real file proof"}]
            ),
            "workspace_folder": str(root),
        },
    )
    assert response.status == 200, await response.text()
    return await response.json()


async def wait_for(predicate):
    for _ in range(300):
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("isolated goal did not reach expected state")


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["once", "deny", "cancel"])
async def test_real_write_dispatch_waits_for_authenticated_owner(tool_bridge, decision):
    client, app, root = tool_bridge
    result = await start(client, root)
    assert result["execution_mode"] == "policy_controlled_tools"
    await wait_for(lambda: bool(app.store.list_pending_approvals()))
    approval = app.store.list_pending_approvals()[0]["approval_id"]
    target = root / "proof.txt"
    assert not target.exists()
    for caller in ("ares", "grokbot", "mcp"):
        response = await client.post(
            f"/v1/approvals/{approval}", headers=h(caller), json={"decision": "once"}
        )
        assert response.status == 403
    for endpoint in ("/v1/agent-goals/write1", "/v1/agent-goals/write1/cancel"):
        response = await (
            client.post(endpoint, headers=h("grokbot"), json={})
            if endpoint.endswith("cancel")
            else client.get(endpoint, headers=h("grokbot"))
        )
        assert response.status == 404
    if decision == "cancel":
        assert (
            await client.post("/v1/agent-goals/write1/cancel", headers=h(), json={})
        ).status == 200
    else:
        response = await client.post(
            f"/v1/approvals/{approval}", headers=h("cli"), json={"decision": decision}
        )
        assert response.status == 200, await response.text()
    await wait_for(
        lambda: (
            app.store.get_request("agent-ares-write1")["status"]
            in {"completed", "cancelled"}
        )
    )
    assert target.exists() is (decision == "once")
    if decision == "once":
        assert target.read_text() == "real file proof"
        assert any(
            json.loads(m["content"]).get("written") is True for m in app.fixture_calls
        )
    payload = await (await client.get("/v1/agent-goals/write1", headers=h())).json()
    # This scripted model has no canonical owner verifier; its claim cannot verify.
    assert payload["execution_verified"] is False
    assert payload["status"] == (
        "cancelled" if decision == "cancel" else "completed_unverified"
    )
    assert not app.store.list_pending_approvals()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["absolute", "relative", "symlink", "exec", "rea"])
async def test_foreign_paths_and_unsupported_tools_never_dispatch(tool_bridge, kind):
    client, app, root = tool_bridge
    outside = root.parent / "foreign.txt"
    link = root / "escape"
    link.symlink_to(root.parent, target_is_directory=True)
    name = "write_file"
    path = {
        "absolute": str(outside),
        "relative": "../foreign.txt",
        "symlink": "escape/foreign.txt",
    }.get(kind, "proof.txt")
    if kind == "exec":
        name = "terminal"
    if kind == "rea":
        name = "mcp__rea__open_binary"
    await start(client, root, name, {"path": path, "content": "denied"})
    await wait_for(
        lambda: app.store.get_request("agent-ares-write1")["status"] == "completed"
    )
    assert not outside.exists() and not (root / "proof.txt").exists()
    assert not app.store.list_pending_approvals()


def test_model_fields_never_verify_and_exact_supported_catalog():
    output = project_goal(
        "g",
        "t",
        {
            "status": "completed",
            "result": {
                "task_state": "completed_verified",
                "receipt": {"verification": "verified"},
                "execution_verified": True,
            },
        },
    )
    assert output["execution_verified"] is False
    assert set(supported_tools()) == {
        "call_agent",
        "run_team",
        "get_agent_result",
        "read_file",
        "write_file",
        "append_file",
        "patch",
        "delete_file",
        "move_file",
        "copy_file",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["symlink", "kill_switch"])
async def test_recheck_resource_and_kill_switch_after_owner_wait(
    tool_bridge, monkeypatch, change
):
    client, app, root = tool_bridge
    await start(client, root)
    await wait_for(lambda: bool(app.store.list_pending_approvals()))
    approval = app.store.list_pending_approvals()[0]["approval_id"]
    outside = root.parent / "foreign.txt"
    outside.write_text("untouched")
    if change == "symlink":
        (root / "proof.txt").symlink_to(outside)
    else:
        monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "0")
    response = await client.post(
        f"/v1/approvals/{approval}", headers=h("cli"), json={"decision": "once"}
    )
    assert response.status == 200
    await wait_for(
        lambda: app.store.get_request("agent-ares-write1")["status"] == "completed"
    )
    assert outside.read_text() == "untouched"
    assert any(not json.loads(m["content"]).get("written") for m in app.fixture_calls)
    if change == "kill_switch":
        assert not (root / "proof.txt").exists()


@pytest.mark.asyncio
async def test_copy_destination_directory_cannot_follow_nested_symlink(tool_bridge):
    client, app, root = tool_bridge
    (root / "source.txt").write_text("private source")
    destination = root / "destination"
    destination.mkdir()
    outside = root.parent / "foreign.txt"
    outside.write_text("untouched")
    (destination / "source.txt").symlink_to(outside)
    await start(client, root, "copy_file", {"src": "source.txt", "dst": "destination"})
    await wait_for(
        lambda: app.store.get_request("agent-ares-write1")["status"] == "completed"
    )
    assert outside.read_text() == "untouched"
    assert not app.store.list_pending_approvals()


def test_projection_accepts_only_matching_canonical_owner_file_verification(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    gateway.store.ensure_session("ares:proof", workspace=str(tmp_path))
    owner = gateway.task_owner
    task = owner.open_turn(
        session_id="ares:proof",
        request_id="agent-ares-proof",
        text="Write proof.txt",
        strategy="fixture",
        owner="fixture-owner",
        workspace=str(tmp_path),
    )
    target = tmp_path / "proof.txt"
    target.write_text("independently verified artifact")
    owner.store.update_task(
        task.task_id, lambda t: t.payload.update(artifacts=[str(target)])
    )
    task, _ = owner.close_turn(
        task.task_id, {"output": "worker claim"}, status="completed"
    )
    assert task.state.value == "completed_verified"
    receipt = {
        "request_id": "agent-ares-proof",
        "session_id": "ares:proof",
        "status": "completed",
        "result": {"task_id": task.task_id},
    }
    assert (
        project_goal("proof", "thread", receipt, gateway=gateway)["execution_verified"]
        is True
    )
    for mismatch in (
        {"request_id": "agent-grokbot-proof"},
        {"session_id": "grokbot:proof"},
    ):
        assert (
            project_goal("proof", "thread", {**receipt, **mismatch}, gateway=gateway)[
                "execution_verified"
            ]
            is False
        )
