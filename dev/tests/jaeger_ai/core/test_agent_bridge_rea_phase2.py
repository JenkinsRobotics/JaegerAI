"""REA remains unavailable; native goal grants cannot reach any REA provider.

These are denial proofs using test-owned target bytes, not provider acceptance.
"""

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import BaseModel

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.agent_bridge.tool_scope import supported_tools


@pytest.mark.asyncio
async def test_ares_cannot_read_or_mutate_grokbot_fixture_target(tmp_path, monkeypatch):
    from jaeger_agent.tool_executor import AllowlistToolExecutor, DirectToolExecutor
    from jaeger_os.core.tools.tool_registry import register_tool_instance
    from jaeger_os.core.tools.tool_schema import ToolDef

    ares_root, grok_root = tmp_path / "ares", tmp_path / "grokbot"
    ares_root.mkdir()
    grok_root.mkdir()
    private_target = grok_root / "target.bin"
    private_target.write_bytes(b"grok-private-target")
    (ares_root / "escape").symlink_to(grok_root, target_is_directory=True)
    monkeypatch.setenv("JAEGER_AGENT_WEBHOOK_HOST", "")
    monkeypatch.setenv(
        "JAEGER_AGENT_WORKSPACES",
        json.dumps({"ares": [str(ares_root)], "grokbot": [str(grok_root)]}),
    )
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "sessions.db"))
    app.app.on_startup.clear()
    reads = []

    class Args(BaseModel):
        path: str

    def fixture_provider(path):
        reads.append(path)
        return {"content": private_target.read_bytes().decode()}

    rea_tool = ToolDef(
        name="mcp__rea__open_binary",
        description="fixture-only",
        args_model=Args,
        fn=fixture_provider,
    )
    register_tool_instance(rea_tool)

    async def scripted_response(
        session_id, turn_id, text, *, request_id=None, execution=None
    ):
        app.store.complete_request(
            request_id, status="completed", result={"output": "fixture response"}
        )

    app._execute_turn_inner = scripted_response
    async with TestClient(TestServer(app.app)) as client:
        for caller in ("ares", "grokbot"):
            response = await client.post(
                "/v1/agent-messages",
                headers=caller_auth.client_headers(caller),
                json={
                    "id": caller,
                    "thread": f"{caller}-thread",
                    "to": "jaegerd",
                    "kind": "task",
                    "title": "Fixture",
                    "body": "No provider execution",
                },
            )
            assert response.status == 200
        ares = caller_auth.client_headers("ares")
        base = {
            "id": "analysis",
            "thread": "ares-thread",
            "goal": "analyze target",
            "workspace_folder": str(ares_root),
        }
        assert (
            await client.post(
                "/v1/agent-goals",
                headers=ares,
                json={**base, "rea_tools": ["open_binary"]},
            )
        ).status == 501
        assert (
            await client.post(
                "/v1/agent-goals",
                headers=ares,
                json={
                    **base,
                    "workspace_folder": str(grok_root),
                    "rea_tools": ["open_binary"],
                },
            )
        ).status == 403
        assert (
            await client.post(
                "/v1/agent-goals",
                headers=ares,
                json={
                    **base,
                    "workspace_folder": str(ares_root / "escape"),
                    "rea_tools": ["open_binary"],
                },
            )
        ).status == 403
        assert (
            await client.post(
                "/v1/agent-goals",
                headers=ares,
                json={**base, "rea_tools": ["extract_artifact"]},
            )
        ).status == 403
        assert (
            await client.get("/v1/agent-threads/grokbot-thread", headers=ares)
        ).status == 404
        assert (
            await client.post("/v1/agent-goals", headers=ares, json=base)
        ).status == 200
        await asyncio.sleep(0.02)
        grant = app.store.get_request("agent-ares-analysis")["execution"][
            "allowed_tools"
        ]
        assert set(grant) == set(supported_tools())
        assert not any(name.startswith("mcp__") for name in grant)
        result = AllowlistToolExecutor(DirectToolExecutor(), frozenset(grant)).execute(
            rea_tool, {"path": str(private_target)}
        )
        assert result["error_type"] == "permission_denied"
    assert reads == []
    assert private_target.read_bytes() == b"grok-private-target"
