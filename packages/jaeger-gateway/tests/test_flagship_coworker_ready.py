"""Verification tests for Hybrid Model Routing, Living Avatar Link, Starter Skills, Onboarding & Return Briefing."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_avatar import AvatarLink
from jaeger_gateway.runtime import ModularGatewayRuntime
from jaeger_models import HybridRoutingStore, StickyFallbackModel
from jaeger_skills import STARTER_SKILLS, ensure_starter_skills


def test_starter_skills_seeded_and_non_overwriting(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    res1 = ensure_starter_skills(skills_dir)
    assert set(res1["installed"]) == set(STARTER_SKILLS.keys())
    assert res1["skipped"] == []

    # Customize one skill and confirm re-seeding preserves user edits
    custom = skills_dir / "morning-briefing" / "SKILL.md"
    custom.write_text("---\nname: morning-briefing\ndescription: Custom\n---\n\nMy custom brief.\n", encoding="utf-8")
    res2 = ensure_starter_skills(skills_dir)
    assert res2["installed"] == []
    assert "morning-briefing" in res2["skipped"]
    assert "My custom brief." in custom.read_text(encoding="utf-8")


def test_hybrid_routing_store_persistence(tmp_path: Path) -> None:
    store = HybridRoutingStore(tmp_path)
    updated = store.update(
        primary="mistral-large-4:cloud",
        background="qwen3:8b",
        vision="qwen3-vl:8b-instruct",
        fallback="gemma4:12b",
    )
    assert updated.primary == "mistral-large-4:cloud"
    assert updated.background == "qwen3:8b"
    assert updated.fallback == "gemma4:12b"

    reloaded = HybridRoutingStore(tmp_path).load()
    assert reloaded == updated


def test_avatar_link_loopback_control(tmp_path: Path) -> None:
    received: list[dict[str, Any]] = []
    expected_token = "tok_test_avatar_123"

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, _fmt: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                body = json.dumps({"ok": True}).encode()
            elif self.path == "/control/state":
                body = json.dumps({"emotion": "warm", "face": "vita"}).encode()
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("X-Avatar-Token") != expected_token:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"bad token"}')
                return
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            received.append(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "echo": payload}).encode())

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / "avatar_link.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{port}", "token": expected_token}),
            encoding="utf-8",
        )
        link = AvatarLink(state_dir=tmp_path)
        assert link.is_alive() is True
        assert link.feel("happy")["ok"] is True
        assert link.react("nod")["ok"] is True
        assert link.gaze(0.2, -0.1)["ok"] is True
        assert link.stop()["ok"] is True
        assert link.state()["face"] == "vita"
        assert [r["op"] for r in received] == ["emotion", "reaction", "gaze", "stop"]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_gateway_hybrid_routing_onboarding_and_briefing(tmp_path: Path) -> None:
    rt = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path)
    app = rt.build_app()
    try:
        async with TestClient(TestServer(app)) as client:
            # 1. Starter skills are seeded automatically
            skills_resp = await client.get("/v1/skills")
            assert skills_resp.status == 200
            skills_data = await skills_resp.json()
            names = {s["name"] for s in skills_data["skills"]}
            assert "morning-briefing" in names
            assert "code-debug-verify" in names

            # 2. Hybrid routing GET & PUT + StickyFallbackModel activation
            r_put = await client.put(
                "/v1/models/routing",
                json={
                    "primary": "mistral-large-4:cloud",
                    "background": "qwen3:8b",
                    "vision": "qwen3-vl:8b-instruct",
                    "fallback": "gemma4:12b",
                },
            )
            assert r_put.status == 200
            r_data = await r_put.json()
            assert r_data["routing"]["primary"] == "mistral-large-4:cloud"
            assert r_data["routing"]["background"] == "qwen3:8b"
            assert r_data["routing"]["fallback"] == "gemma4:12b"
            assert isinstance(rt.model, StickyFallbackModel)

            # 3. Day-1 onboarding status -> complete -> verified state
            ob0 = await (await client.get("/v1/onboarding/status")).json()
            assert ob0["ok"] is True
            assert ob0["starter_skills_count"] >= len(STARTER_SKILLS)

            ob1 = await client.post(
                "/v1/onboarding/complete",
                json={
                    "owner_name": "Alex",
                    "ai_name": "Nova",
                    "mission": "Help ship clean modular software",
                    "first_goal": "Prepare Q4 engineering roadmap",
                    "first_goal_domain": "work",
                    "autonomy_enabled": True,
                },
            )
            assert ob1.status == 200
            ob1_data = await ob1.json()
            assert ob1_data["completed"] is True
            assert ob1_data["identity"]["owner_name"] == "Alex"
            assert ob1_data["identity"]["ai_name"] == "Nova"
            assert ob1_data["active_goals_count"] == 1

            # 4. Return briefing includes personalized greeting & active goal
            br = await client.get("/v1/cognition/briefing")
            assert br.status == 200
            br_data = await br.json()
            assert br_data["ok"] is True
            assert "Welcome back, Alex" in br_data["summary"]
            assert "Prepare Q4 engineering roadmap" in br_data["summary"]
            assert len(br_data["active_goals"]) == 1
    finally:
        rt.close()
