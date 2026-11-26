"""Phase 4 E2E tests: Business Team, Budgets, YouTube Studio, Channels & Hermes Secret Redaction."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime


@pytest.mark.asyncio
async def test_gateway_phase4_business_youtube_and_channels(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            # 1. Business team & project budget enforcement
            r_team = await client.get("/v1/business/team")
            assert r_team.status == 200
            d_team = await r_team.json()
            assert len(d_team["team"]) == 8

            r_proj = await client.post(
                "/v1/business/projects",
                json={"name": "Jaeger Robotics YouTube", "kind": "youtube_channel", "budget_usd": 40.0},
            )
            assert r_proj.status == 201
            pid = (await r_proj.json())["project"]["project_id"]

            r_spend_denied = await client.post(
                "/v1/business/spend",
                json={"project_id": pid, "role_id": "designer", "amount_usd": 5.0, "description": "Fonts"},
            )
            assert r_spend_denied.status == 403

            r_spend_ok = await client.post(
                "/v1/business/spend",
                json={
                    "project_id": pid,
                    "role_id": "designer",
                    "amount_usd": 5.0,
                    "description": "Fonts",
                    "approved_by": "owner",
                },
            )
            assert r_spend_ok.status == 200

            # 2. YouTube Studio Episode + Approval Gate + 32GB Phased Research Plan
            r_yt_tools = await client.get("/v1/youtube/tools")
            assert r_yt_tools.status == 200
            assert (await r_yt_tools.json())["tools"]["memory_policy"] == "single_heavy_model_per_phase_32gb"

            r_plan = await client.post(
                "/v1/youtube/research/plan",
                json={"source": "PL1234567890", "video_ids": ["dQw4w9WgXcQ"]},
            )
            assert r_plan.status == 200
            assert (await r_plan.json())["plan"]["max_concurrent_heavy_models"] == 1

            r_ep = await client.post(
                "/v1/youtube/episodes",
                json={"title": "Ep 1: 24/7 Local Autonomous Agent on 32GB Mac", "target_duration_s": 540},
            )
            assert r_ep.status == 201
            ep = (await r_ep.json())["episode"]
            eid = ep["episode_id"]
            assert len(ep["timeline_clips"]) >= 4

            r_pub_blocked = await client.post(
                f"/v1/youtube/episodes/{eid}/advance",
                json={"stage": "ready_to_publish"},
            )
            assert r_pub_blocked.status == 403

            r_pub_ok = await client.post(
                f"/v1/youtube/episodes/{eid}/advance",
                json={"stage": "ready_to_publish", "owner_approved": True, "approval_note": "Approved"},
            )
            assert r_pub_ok.status == 200
            assert (await r_pub_ok.json())["episode"]["owner_approved"] is True

            # 3. Channels outbox scrubs secrets and gates external sends
            r_msg = await client.post(
                "/v1/channels/send",
                json={
                    "channel": "imessage",
                    "recipient": "owner",
                    "body": "Upload ready! Token sk-proj-99998888777766665555",
                    "approved": False,
                },
            )
            assert r_msg.status == 201
            d_msg = (await r_msg.json())["message"]
            assert d_msg["status"] == "queued_for_approval"
            assert "999988887777" not in d_msg["body"]
    finally:
        rt.close()
