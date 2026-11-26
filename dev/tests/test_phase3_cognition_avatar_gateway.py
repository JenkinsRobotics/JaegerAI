"""Phase 3 tests: Cognitive Life Loop, World Model, Avatar Store, Kokoro visemes, and live Gateway APIs."""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway import ModularGatewayRuntime


def _make_minimal_vrm_glb() -> bytes:
    """Create a tiny valid GLB container with VRM 1.0 metadata for upload/serve tests."""
    doc = {
        "asset": {"version": "2.0"},
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {"name": "JaegerTestVRM", "authors": ["JaegerAI"]},
            }
        },
    }
    raw_json = json.dumps(doc).encode("utf-8")
    pad = (4 - (len(raw_json) % 4)) % 4
    chunk_data = raw_json + (b" " * pad)
    total_len = 12 + 8 + len(chunk_data)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    chunk_hdr = struct.pack("<I4s", len(chunk_data), b"JSON")
    return header + chunk_hdr + chunk_data


@pytest.mark.asyncio
async def test_gateway_phase3_cognition_and_avatar_endpoints(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    try:
        app = rt.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            # 1. Cognitive life loop runs independently on startup and reports world model state
            r_cog = await client.get("/v1/cognition/state")
            assert r_cog.status == 200
            d_cog = await r_cog.json()
            assert d_cog["ok"] is True
            assert "cognition" in d_cog and "world" in d_cog

            # 2. External multimodal perception ingestion updates world model immediately
            r_perc = await client.post(
                "/v1/cognition/perceive",
                json={
                    "modality": "camera",
                    "kind": "person_detected",
                    "payload": {"zone": "desk", "confidence": 0.96},
                    "salience": 0.85,
                },
            )
            assert r_perc.status == 201
            d_perc = await r_perc.json()
            assert d_perc["ok"] is True
            assert d_perc["perception"]["modality"] == "camera"

            r_cog2 = await client.get("/v1/cognition/state")
            d_cog2 = await r_cog2.json()
            assert any(p["kind"] == "person_detected" for p in d_cog2["perceptions"])

            # 3. Default Jaeger avatar profile + live expression update
            r_av = await client.get("/v1/avatars/jaeger")
            assert r_av.status == 200
            d_av = await r_av.json()
            assert d_av["ok"] is True
            assert d_av["agent_id"] == "jaeger"

            r_live = await client.put(
                "/v1/avatars/jaeger/live",
                json={"emotion": "happy", "intensity": 0.8, "state": "speaking", "amplitude": 0.6},
            )
            assert r_live.status == 200
            d_live = await r_live.json()
            assert d_live["live"]["emotion"] == "happy"
            assert d_live["live"]["state"] == "speaking"

            # 4. Kokoro viseme lip-sync timeline endpoint
            r_vis = await client.get("/v1/avatars/jaeger/visemes?text=Hello+Jaeger")
            assert r_vis.status == 200
            d_vis = await r_vis.json()
            assert d_vis["ok"] is True
            assert d_vis["duration_ms"] > 0
            assert len(d_vis["frames"]) > 0

            # 5. Upload VRM 1.0 GLB asset, bind to Jaeger, and serve binary back
            vrm_bytes = _make_minimal_vrm_glb()
            r_up = await client.post(
                "/v1/avatars/assets",
                json={"name": "jaeger_studio.vrm", "data_base64": base64.b64encode(vrm_bytes).decode("ascii")},
            )
            assert r_up.status == 201
            asset = (await r_up.json())["asset"]
            assert asset["format"] == "vrm"
            sha = asset["sha256"]

            r_bind = await client.put(
                "/v1/avatars/jaeger",
                json={"asset_sha": sha, "mode": "3d_vrm", "display_name": "Jaeger Studio", "preset": "studio_cel"},
            )
            assert r_bind.status == 200
            assert (await r_bind.json())["avatar"]["mode"] == "3d_vrm"

            r_file = await client.get(f"/v1/avatars/assets/{sha}/file")
            assert r_file.status == 200
            assert await r_file.read() == vrm_bytes
    finally:
        rt.close()
