"""Phase 5 E2E tests: Unified EmbodimentPort (Minecraft + JP01), E-Stop Cascade, Voice Presence & Vision."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime


@pytest.mark.asyncio
async def test_gateway_phase5_embodiment_estop_and_presence(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            # 1. Both Minecraft & JP01 embodiments + voice + vision live in unified status
            r_st = await client.get("/v1/embodiment/status")
            assert r_st.status == 200
            d_st = await r_st.json()
            assert d_st["minecraft"]["bridge"]["bridge_present"] is True
            assert d_st["jp01"]["dry_run"] is True
            assert d_st["vision"]["max_frames"] == 6

            # 2. Act in Minecraft & persist checkpoint
            r_mc = await client.post(
                "/v1/embodiment/minecraft/act",
                json={"action": "set_goal", "params": {"goal": "Build automated wheat farm"}},
            )
            assert r_mc.status == 200
            r_cp = await client.post("/v1/embodiment/minecraft/checkpoint", json={"reason": "test_save"})
            assert r_cp.status == 200 and (await r_cp.json())["ok"] is True

            # 3. Act on JP01 hardware (dry-run bracket frame)
            r_jp = await client.post(
                "/v1/embodiment/jp01/act",
                json={"action": "head_move", "params": {"pan_deg": 110, "tilt_deg": 85, "speed": 30}},
            )
            assert r_jp.status == 200
            assert (await r_jp.json())["frame"] == "MJ[110,85,30]"

            # 4. System E-Stop latches Governor + Minecraft + JP01 simultaneously!
            r_es = await client.post("/v1/system/estop", json={"active": True, "reason": "bench_safety"})
            assert r_es.status == 200

            assert (await client.post("/v1/embodiment/minecraft/act", json={"action": "move_to"})).status == 409
            assert (await client.post("/v1/embodiment/jp01/act", json={"action": "head_move"})).status == 409

            # Release E-Stop -> both embodiments unlock
            assert (await client.post("/v1/system/estop", json={"active": False})).status == 200
            assert (await client.post("/v1/embodiment/jp01/act", json={"action": "face_expression", "params": {"mood": "warm"}})).status == 200

            # 5. 24/7 Ambient Speech Gate (<ignore> vs <reply>)
            r_ign = await client.post("/v1/presence/voice/hear", json={"transcript": "did you see the game last night"})
            assert r_ign.status == 200 and (await r_ign.json())["decision"]["action"] == "ignore"
            r_rep = await client.post("/v1/presence/voice/hear", json={"transcript": "Hey Jaeger how is the YouTube script"})
            assert r_rep.status == 200 and (await r_rep.json())["decision"]["action"] == "reply"
    finally:
        rt.close()
