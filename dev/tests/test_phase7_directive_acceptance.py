"""Directive §13 integrated acceptance tests: Identity persistence, Character overlays, MCP hot-reload, Droid Mode, OTIO & Media Archive."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime


@pytest.mark.asyncio
async def test_directive_acceptance_identity_mcp_droid_and_otio(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"

    # --- Boot 1: Configure user identity, character overlay, MCP server, episode & media archive ---
    rt1 = ModularGatewayRuntime(state_dir=state_dir, workspace=tmp_path)
    try:
        app1 = rt1.build_app(serve_ui=False)
        async with TestClient(TestServer(app1)) as client:
            # 1. Default platform has ZERO hardcoded founder identity
            r_id0 = await client.get("/v1/identity")
            assert r_id0.status == 200
            d_id0 = await r_id0.json()
            assert d_id0["identity"]["ai_name"] == "Jaeger"
            assert d_id0["identity"]["owner_name"] == "Owner"

            # 2. Any user configures their own digital counterpart + channels without touching source code
            r_put = await client.put(
                "/v1/identity",
                json={
                    "ai_name": "ARES",
                    "owner_name": "Alex",
                    "objectives": ["Ship Episode 01", "Build JP01"],
                    "channels": [{"name": "Robotics Lab", "theme": "engineering"}],
                },
            )
            assert r_put.status == 200

            # 3. Summon an expressive character overlay (preserves truthfulness & memory!)
            r_ch = await client.post(
                "/v1/identity/character",
                json={"character_id": "mentor", "name": "Chief Engineer", "style": "Crisp, technical, encouraging"},
            )
            assert r_ch.status == 201
            r_id1 = await client.get("/v1/identity")
            d_id1 = await r_id1.json()
            assert "ARES" in d_id1["compiled_prompt"]
            assert "Chief Engineer" in d_id1["compiled_prompt"]
            assert "Truthfulness invariant" in d_id1["compiled_prompt"]

            # 4. Register a future Jenkins Robotics MCP endpoint (AetherStudio / Blender / Resolve)
            r_mcp = await client.post(
                "/v1/mcp/servers",
                json={
                    "name": "aether_studio",
                    "transport": "streamable_http",
                    "url": "http://127.0.0.1:8780/mcp",
                    "headers": {"X-Workspace": "default"},
                    "connect": False,
                },
            )
            assert r_mcp.status == 201
            assert (state_dir / "mcp_servers.json").is_file()

            # 5. Host Droid Mode embodiment (gimbal look_at + E-Stop cascade)
            r_act = await client.post(
                "/v1/embodiment/droid/act",
                json={"action": "look_at", "params": {"pan_deg": 35, "tilt_deg": 12, "zoom": 1.5}},
            )
            assert r_act.status == 200
            assert (await r_act.json())["pose"]["pan_deg"] == 35.0

            await client.post("/v1/system/estop", json={"active": True, "reason": "camera_privacy"})
            assert (await client.post("/v1/embodiment/droid/act", json={"action": "center"})).status == 409
            await client.post("/v1/system/estop", json={"active": False})
            assert (await client.post("/v1/embodiment/droid/act", json={"action": "center"})).status == 200

            # 6. Episode 01 OTIO timeline export + Media Archive (genuine vs reconstructed provenance)
            r_ep = await client.post(
                "/v1/youtube/episodes",
                json={"title": "Episode 01 — Awakening", "target_duration_s": 360},
            )
            eid = (await r_ep.json())["episode"]["episode_id"]

            r_otio = await client.get(f"/v1/youtube/episodes/{eid}/otio?fps=24")
            assert r_otio.status == 200
            otio = (await r_otio.json())["otio"]
            assert otio["OTIO_SCHEMA"] == "Timeline.1"
            assert otio["name"] == "Episode 01 — Awakening"
            assert len(otio["tracks"]["children"]) >= 3

            r_med = await client.post(
                "/v1/media/archive",
                json={
                    "kind": "camera",
                    "source_path": "/recordings/ep01_desk_scene6.mov",
                    "project_id": eid,
                    "scene_description": "Hard cut to real Mac Studio desk and Insta360 gimbal camera",
                    "is_reconstructed": False,
                    "tags": ["ep01", "scene6", "reality"],
                },
            )
            assert r_med.status == 201
    finally:
        rt1.close()

    # --- Boot 2: Simulate full process restart -> verify durable persistence (§13) ---
    rt2 = ModularGatewayRuntime(state_dir=state_dir, workspace=tmp_path)
    try:
        app2 = rt2.build_app(serve_ui=False)
        async with TestClient(TestServer(app2)) as client:
            d_id = (await (await client.get("/v1/identity")).json())["identity"]
            assert d_id["ai_name"] == "ARES"
            assert d_id["owner_name"] == "Alex"
            assert d_id["active_character_id"] == "mentor"

            d_med = await (await client.get("/v1/media/archive?q=Insta360")).json()
            assert d_med["count"] == 1
            assert d_med["items"][0]["is_reconstructed"] is False
    finally:
        rt2.close()
