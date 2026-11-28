"""Tests for D-J ecosystem integrations: jaeger-chat OpenAI/SSE compat, JaegerArena preset, board, reminders & JaegerClient."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import JaegerClient, ModularGatewayRuntime
from jaeger_mcp import build_preset_config, list_mcp_presets
from jaeger_models import ReplayModel


def test_jaeger_arena_mcp_preset() -> None:
    presets = {p["preset_id"]: p for p in list_mcp_presets()}
    assert "jaeger_arena" in presets
    assert presets["jaeger_arena"]["default_url"] == "http://127.0.0.1:8792/mcp/"
    cfg = build_preset_config("jaeger_arena", bearer_token="arena-tok-123")
    assert cfg.headers["Authorization"] == "Bearer arena-tok-123"
    assert cfg.transport == "streamable_http"


@pytest.mark.asyncio
async def test_jaeger_chat_openai_compat_board_reminders_and_python_client(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    rt.model = ReplayModel(
        [
            {"content": "Hello from Jaeger!"},
            {"content": "Streamed reply from Jaeger!"},
            {"content": "Client SDK reply!"},
        ],
        model_id="local/test",
    )
    try:
        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            # 1. GET /v1/models carries OpenAI-compatible `data` for jaeger-chat VS Code tab
            r_models = await client.get("/v1/models")
            assert r_models.status == 200
            m_json = await r_models.json()
            assert any(item["id"] == "jaeger" for item in m_json["data"])

            # 2. POST /v1/chat/completions non-streaming
            r_cmp = await client.post(
                "/v1/chat/completions",
                json={"model": "jaeger", "stream": False, "messages": [{"role": "user", "content": "Hi"}]},
            )
            assert r_cmp.status == 200
            c_json = await r_cmp.json()
            assert c_json["choices"][0]["message"]["content"] == "Hello from Jaeger!"

            # 3. POST /v1/chat/completions streaming SSE
            r_stream = await client.post(
                "/v1/chat/completions",
                json={"model": "jaeger", "stream": True, "messages": [{"role": "user", "content": "Stream"}]},
            )
            assert r_stream.status == 200
            body_text = await r_stream.text()
            assert "Streamed reply from Jaeger!" in body_text and "data: [DONE]" in body_text

            # 4. /v1/sessions/{id}/stream SSE alias
            sid = rt.store.main_chat_session()["session_id"]
            r_sse = await client.get(f"/v1/sessions/{sid}/stream?once=1")
            assert r_sse.status == 200

            # 5. Kanban board & one-shot reminders routes
            r_card = await client.post("/v1/board/cards", json={"title": "Ship JaegerAI 1.0", "column": "todo"})
            assert r_card.status == 201
            card_id = (await r_card.json())["card"]["card_id"]
            r_mv = await client.post(f"/v1/board/cards/{card_id}/move", json={"column": "done"})
            assert r_mv.status == 200 and (await r_mv.json())["card"]["column"] == "done"

            r_rem = await client.post("/v1/reminders", json={"message": "Check build", "in_minutes": 5})
            assert r_rem.status == 201
            r_list = await client.get("/v1/reminders")
            assert (await r_list.json())["count"] == 1

            # 6. Zero-dependency JaegerClient talking to live TestServer!
            base_url = str(client.make_url("")).rstrip("/")
            sdk = JaegerClient(base_url=base_url)
            ans = await asyncio.to_thread(sdk.ask, "Ping via SDK")
            assert ans == "Client SDK reply!"
            board_via_sdk = await asyncio.to_thread(sdk.board)
            assert board_via_sdk["counts"]["done"] == 1
    finally:
        rt.close()
