"""End-to-end integration test for the 100% standalone modular JaegerAI stack."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime
from jaeger_models import ReplayModel


@pytest.mark.asyncio
async def test_modular_gateway_runtime_end_to_end(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "hello.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")

    runtime = ModularGatewayRuntime(
        state_dir=tmp_path / "state",
        workspace=ws,
    )
    # Inject deterministic ReplayModel exercising real built-in tools -> final answer
    runtime.model = ReplayModel([
        {
            "content": "",
            "thinking": "Inspecting hello.py first.",
            "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "hello.py"}}],
        },
        {
            "content": "Read hello.py successfully; greet() returns 'hi'.",
            "tool_calls": [],
        },
    ])

    app = runtime.build_app(serve_ui=False)
    try:
        async with TestClient(TestServer(app)) as client:
            health = await (await client.get("/health")).json()
            assert health["ok"] is True
            assert health["architecture"] == "modular-standalone"
            assert health["tools_count"] >= 10

            tools_data = await (await client.get("/v1/tools")).json()
            tool_names = {t["name"] for t in tools_data["tools"]}
            assert {"read_file", "edit_file", "apply_patch", "shell", "repo_map", "memory_remember"} <= tool_names

            # Create session and run real modular AgentLoop turn
            sess = (await (await client.post("/v1/sessions", json={"title": "E2E"})).json())["session"]
            sid = sess["session_id"]

            run = await (
                await client.post(
                    f"/v1/sessions/{sid}/runs",
                    json={"prompt": "Read hello.py", "wait": True},
                )
            ).json()
            assert run["ok"] is True
            assert "greet()" in run["result"]["content"]

            # Verify SSE replay captured thinking, tool call, text, and completion
            sse = await (await client.get(f"/v1/sessions/{sid}/events?once=1")).text()
            assert "event: run.started" in sse
            assert "event: thinking.delta" in sse
            assert "event: tool.started" in sse
            assert "event: tool.completed" in sse
            assert "event: text.delta" in sse
            assert "event: run.completed" in sse

            # Verify durable memory facts API
            assert (await client.post("/v1/memory/facts", json={"key": "lang", "value": "python"})).status == 201
            facts = (await (await client.get("/v1/memory/facts")).json())["facts"]
            assert any(f["key"] == "lang" and f["value"] == "python" for f in facts)
    finally:
        runtime.close()
