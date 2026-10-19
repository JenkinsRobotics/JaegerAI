"""Full isolated Gateway -> EntityRuntime OWNER -> real native tool acceptance.

Model-client/adapter selection and peripheral capability inventory are fixtures.
Execution, policy, approval,
TaskOwner, SqliteRunStore, native tools and result projection stay real.
"""

import asyncio
import hashlib
import inspect
import json
import socket
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from jaeger_agent import ProviderAdapter

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class OwnerModel(ProviderAdapter):
    name = "test-only-owner-model"

    def __init__(self):
        self.calls = 0
        self.seen_results = []

    def format_messages(self, messages, tools, system):
        return {"messages": messages}

    def call(self, formatted, interrupt_event, **kwargs):
        self.calls += 1
        assert self.calls <= 8, "unexpected model continuation"
        messages = formatted["messages"]
        results = [
            json.loads(m["content"]) for m in messages if m.get("role") == "tool"
        ]
        self.seen_results = results
        if self.calls in (1, 2, 4) and not any(
            row.get("written") is False or row.get("ok") is False for row in results
        ):
            tool = "write_file" if self.calls == 1 else "read_file"
            args = {"path": "owner-proof.txt"}
            if tool == "write_file":
                args["content"] = "actual OWNER approval proof\n"
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"owner-fixture-{self.calls}",
                        "name": tool,
                        "arguments": args,
                    }
                ],
            }
        blocked = any(
            result.get("written") is False or result.get("ok") is False
            for result in results
        )
        return {
            "role": "assistant",
            "content": "Blocked: permission denied."
            if blocked
            else "Completed; checked owner-proof.txt.",
        }

    def parse_response(self, response):
        return response

    def supports(self, feature):
        return False


@pytest_asyncio.fixture
async def owner_bridge(tmp_path, monkeypatch):
    from jaeger_agent.core import workspace
    from jaeger_agent.loop import runtime_bridge
    from jaeger_agent.memory import sqlite_store

    from jaeger_ai import main
    from jaeger_ai.core.entity import owner_agent, resident
    from jaeger_ai.core.entity import runtime as runtime_module
    from jaeger_ai.core.entity.ownership import EntityRuntimeMode
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config, dump_yaml
    from jaeger_ai.core.models import external_model, router
    from jaeger_ai.core.runtime import truth

    # Inventory is enrichment, not part of this execution acceptance. Never
    # probe operator model/framework services while assembling the prompt.
    monkeypatch.setattr(truth, "framework_inventory", lambda **_k: [])
    monkeypatch.setattr(
        truth, "provider_model_inventory", lambda *_a, **_k: {"active": {}}
    )
    original_connect = socket.socket.connect
    allowed_ports = set()

    def connect(sock, address):
        if not (
            isinstance(address, tuple)
            and address[0] in ("127.0.0.1", "::1")
            and address[1] in allowed_ports
        ):
            raise AssertionError("Acceptance test attempted non-owned connection")
        return original_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(workspace, "_layout", workspace._layout)
    instance = tmp_path / "owner-instance"
    instance.mkdir()
    layout = InstanceLayout(root=instance)
    for folder in (
        layout.run_dir,
        layout.logs_dir,
        layout.skills_dir,
        layout.workspace_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    config = Config(
        instance_name="bridgeproof", model={"model_path": str(instance / "NO_MODEL")}
    )
    config.skills.run_smoke_tests = False
    config.skills.enabled_base_skills = ["fixture-no-shipped-code"]
    config.external_model.enabled = True
    config.external_model.provider = "openai"
    config.external_model.model = "fixture-only"
    config.external_model.ctx = 131072
    config.external_model.fallback = []
    config.automation.interaction_tier = "agent"
    config.automation.autonomy = "ask"
    dump_yaml(layout.config_path, config)
    layout.mcp_config_path.write_text('{"version":1,"servers":[]}')
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(instance))
    monkeypatch.setenv("JAEGER_AGENT_WEBHOOK_HOST", "")
    monkeypatch.setenv("JAEGER_OWNER_REACT", "1")
    monkeypatch.setenv("JAEGER_AGENT_BRIDGE", "1")
    monkeypatch.setenv(
        "JAEGER_AGENT_WORKSPACES", json.dumps({"ares": [str(layout.workspace_dir)]})
    )
    monkeypatch.setenv("JAEGER_TEST_HEADLESS", "1")
    monkeypatch.setattr(runtime_module, "instance_layout", lambda: layout)
    # Only the process-local test instance is bound; never attach to a resident.
    runtime = runtime_module.EntityRuntime(
        state_root=instance / "entity-state", mode=EntityRuntimeMode.OWNER
    )
    monkeypatch.setattr(runtime_module.EntityRuntime, "_instance", runtime)
    monkeypatch.setattr(main, "_pipeline", {})
    owner_agent._reset_for_tests()
    model = OwnerModel()
    client = SimpleNamespace(
        kind="external",
        provider="openai",
        model_name="fixture-only",
        ext=config.external_model,
        num_ctx=131072,
    )
    client.chat = lambda *_a, **_k: "Completed; checked owner-proof.txt."
    monkeypatch.setattr(external_model, "ExternalModelClient", lambda *_a, **_k: client)
    monkeypatch.setattr(router, "select_client", lambda selected, *_a, **_k: selected)
    stacks = []

    def select_adapter(*_args, **_kwargs):
        stacks.append([frame.function for frame in inspect.stack()])
        return model

    monkeypatch.setattr(runtime_bridge, "_adapter_for_client", select_adapter)
    app = JaegerGatewayApp(store=GatewaySessionStore(instance / "gateway.sqlite3"))
    app.app.on_startup.clear()  # no daemon recovery/background/provider prewarm
    app._schedule_summary = lambda *_a: None  # no extra model background summary
    assert app._execute_turn_inner.__func__ is JaegerGatewayApp._execute_turn_inner
    assert app._owner_react_turn.__func__ is JaegerGatewayApp._owner_react_turn
    assert (
        runtime.run_subordinate_react.__func__
        is runtime_module.EntityRuntime.run_subordinate_react
    )
    async with TestClient(TestServer(app.app)) as client_http:
        allowed_ports.add(client_http.make_url("/").port)
        app._loop = asyncio.get_running_loop()
        yield client_http, app, runtime, model, stacks
    for task in list(app._running_tasks.values()):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    owner_agent._reset_for_tests()
    resident.release_resident()
    sqlite_store.close()


async def wait_for(predicate, app):
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail(
        f"OWNER path did not reach expected state; receipts={app.store.get_request('agent-ares-owner-proof')}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["once", "deny", "cancel"])
async def test_real_owner_runtime_write_approval_lifecycle(
    owner_bridge, decision, record_property
):
    client, app, runtime, model, stacks = owner_bridge
    headers = caller_auth.client_headers("ares")
    response = await client.post(
        "/v1/agent-messages",
        headers=headers,
        json={
            "id": "owner-task",
            "thread": "owner-thread",
            "to": "jaegerd",
            "kind": "task",
            "title": "Owner path proof",
            "body": "inert fixture message",
        },
    )
    assert response.status == 200
    response = await client.post(
        "/v1/agent-goals",
        headers=headers,
        json={
            "id": "owner-proof",
            "thread": "owner-thread",
            "workspace_folder": str(runtime.layout.workspace_dir),
            "goal": "Write owner-proof.txt containing actual OWNER approval proof, then read it back.",
        },
    )
    assert response.status == 200, await response.text()
    target = runtime.layout.workspace_dir / "owner-proof.txt"
    await wait_for(lambda: bool(app.store.list_pending_approvals()), app)
    assert not target.exists()
    progress_response = await client.get("/v1/agent-goals/owner-proof", headers=headers)
    assert progress_response.status == 200
    progress = await progress_response.json()
    assert (
        progress["thread"] == "owner-thread" and progress["request_status"] == "running"
    )
    assert progress["execution_verified"] is False
    approval = app.store.list_pending_approvals()[0]
    aid = approval["approval_id"]
    assert approval["request_id"] == "agent-ares-owner-proof"
    for caller in ("ares", "grokbot", "mcp"):
        assert (
            await client.post(
                f"/v1/approvals/{aid}",
                headers=caller_auth.client_headers(caller),
                json={"decision": "once"},
            )
        ).status == 403
    if decision == "cancel":
        response = await client.post(
            "/v1/agent-goals/owner-proof/cancel", headers=headers, json={}
        )
        assert response.status == 200
        assert (
            await client.post(
                f"/v1/approvals/{aid}",
                headers=caller_auth.client_headers("cli"),
                json={"decision": "once"},
            )
        ).status == 409
    else:
        assert (
            await client.post(
                f"/v1/approvals/{aid}",
                headers=caller_auth.client_headers("cli"),
                json={"decision": decision},
            )
        ).status == 200
    await wait_for(
        lambda: (
            app.store.get_request("agent-ares-owner-proof")["status"]
            in {"completed", "cancelled", "failed"}
        ),
        app,
    )
    receipt = app.store.get_request("agent-ares-owner-proof")
    result = await (
        await client.get("/v1/agent-goals/owner-proof", headers=headers)
    ).json()
    assert result["thread"] == "owner-thread"
    assert receipt["execution"]["caller"] == "mcp:ares"
    assert (
        app.store.get_session(receipt["session_id"])["metadata"]["agent_id"]
        == "native:jaeger"
    )
    assert receipt["native_session"].startswith(OWNER_RUN_SESSION_PREFIX)
    assert receipt["native_run_id"]
    assert stacks and all(
        name in stacks[0]
        for name in (
            "build_jaeger_agent",
            "run_subordinate_react",
            "_owner_react_turn",
            "_continued_owner_react",
        )
    )
    if decision == "once":
        assert target.read_text() == "actual OWNER approval proof\n"
        assert (
            hashlib.sha256(target.read_bytes()).hexdigest()
            == hashlib.sha256(b"actual OWNER approval proof\n").hexdigest()
        )
        assert any(row.get("written") is True for row in model.seen_results)
        assert any(
            row.get("read") is True and row.get("content") == target.read_text()
            for row in model.seen_results
        )
        assert receipt["status"] == "completed", receipt
        assert receipt["result"]["backend"] == "owner-react"
        assert receipt["result"]["task_state"] == "completed_verified"
        assert result["execution_verified"] is True
    else:
        assert not target.exists()
        assert result["execution_verified"] is False
        if decision == "deny":
            assert receipt["result"]["task_state"] == "blocked"
        else:
            assert receipt["status"] == "cancelled"
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore

    assert SqliteRunStore().get(receipt["native_run_id"]) is not None
    assert not app.store.list_pending_approvals()

    record_property(
        "owner_evidence",
        json.dumps(
            {
                "decision": decision,
                "request_status": receipt["status"],
                "native_session": receipt["native_session"],
                "native_run_id": receipt["native_run_id"],
                "actor": receipt["execution"]["caller"],
                "role": (receipt.get("result") or {}).get("role"),
                "task_id": (receipt.get("result") or {}).get("task_id"),
                "task_state": (receipt.get("result") or {}).get("task_state"),
                "execution_verified": result["execution_verified"],
                "model_calls": model.calls,
                "file_exists": target.exists(),
                "file_sha256": hashlib.sha256(target.read_bytes()).hexdigest()
                if target.exists()
                else None,
                "adapter_factory_stack": stacks[0],
                "written_result": any(
                    row.get("written") is True for row in model.seen_results
                ),
                "read_result": any(
                    row.get("read") is True for row in model.seen_results
                ),
            },
            sort_keys=True,
        ),
    )
