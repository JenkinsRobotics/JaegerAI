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

            # 5. Owner-controlled Elevated Autonomous Mode toggle (non-overridable safety stays intact)
            assert rt._elevated_mode is False  # noqa: SLF001
            el_on = await client.post("/v1/cognition/autonomy", json={"elevated": True})
            assert el_on.status == 200
            el_data = await el_on.json()
            assert el_data["execution_mode"]["elevated"] is True
            assert el_data["execution_mode"]["autonomy_mode"] == "full_access"
            assert el_data["execution_mode"]["sandbox"] == "unconfined"
            # Destructive safety still blocks rm -rf even in elevated mode
            blocked = rt.tools.execute("shell", {"command": "rm -rf /tmp/definitely_not_real"})
            assert not blocked.ok
            el_off = await client.post("/v1/cognition/autonomy", json={"elevated": False})
            assert (await el_off.json())["execution_mode"]["elevated"] is False

            # 6. Live Virtual Office endpoint returns primary mind, 8 team roles & embodiment ops
            off = await client.get("/v1/office/state")
            assert off.status == 200
            off_data = await off.json()
            assert off_data["ok"] is True
            agent_ids = {a["id"] for a in off_data["agents"]}
            assert "jaeger" in agent_ids
            assert "embodiment_ops" in agent_ids
            assert "role_producer" in agent_ids and "role_engineer" in agent_ids
            assert len(off_data["agents"]) >= 10
            assert "budgets" in off_data and isinstance(off_data["activityFeed"], list)

            # 7. Live Self-Awareness, Global Event Spine, Droid Reflex, Unified Skills & MC Radar
            aw = await client.get("/v1/cognition/awareness")
            assert aw.status == 200
            aw_data = await aw.json()
            assert aw_data["ok"] is True
            assert "[Live Self-Awareness Snapshot]" in aw_data["brief"]
            assert aw_data["droid_reflex"]["auto_park_enabled"] is True

            rx_post = await client.post("/v1/droid/reflex", json={"auto_park_enabled": False, "idle_park_s": 180})
            assert rx_post.status == 200
            rx_data = await rx_post.json()
            assert rx_data["reflex"]["auto_park_enabled"] is False
            assert rx_data["reflex"]["idle_park_s"] == 180

            ev_resp = await client.get("/v1/events/recent")
            assert ev_resp.status == 200
            ev_data = await ev_resp.json()
            assert ev_data["ok"] is True
            assert any(e["event"] == "droid.reflex_updated" for e in ev_data["events"])

            # Unified skill search returns both SKILL.md and verified Minecraft skills
            rt.minecraft_skills.upsert_skill(
                name="buildOakShelter",
                description="Gather oak logs and build a cozy survival shelter",
                code="async function buildOakShelter(bot) {}",
                tags=["minecraft", "shelter"],
            )
            unified = rt._search_unified_skills(query="shelter", limit=10)  # noqa: SLF001
            assert any(r["name"] == "buildOakShelter" and r["source"] == "minecraft" for r in unified["results"])

            # Minecraft radar endpoint returns clean standby payload when not connected
            rad = await client.get("/v1/embodiment/minecraft/radar")
            assert rad.status == 200
            rad_data = await rad.json()
            assert rad_data["ok"] is True and "bot" in rad_data and "modes" in rad_data

            # Freeform Minecraft chat bridges cleanly into Jaeger's model & world model
            class _EchoModel:
                name = "test-mc-chat"

                def generate(self, messages, tools=()):
                    return {"content": "I am right behind you, let's gather oak wood!"}

            rt.model = _EchoModel()
            chat_out = rt._handle_minecraft_chat_message("Matthew", "What should we build first?")  # noqa: SLF001
            assert chat_out["acted"] is True
            assert "oak wood" in chat_out["summary"]
            assert any(p.modality == "minecraft" and p.kind == "chat" for p in rt.world.recent_perceptions(limit=5))

            # 8. Ecosystem MCP presets (Aether Studio + REA) & preset upsert
            presets_resp = await client.get("/v1/mcp/presets")
            assert presets_resp.status == 200
            presets_data = await presets_resp.json()
            preset_ids = {p["preset_id"] for p in presets_data["presets"]}
            assert "aether_studio" in preset_ids and "rea" in preset_ids

            add_aether = await client.post(
                "/v1/mcp/servers",
                json={"preset": "aether_studio", "bearer_token": "tok_test", "connect": False},
            )
            assert add_aether.status == 201
            assert any(t["name"] == "inspect_image" for t in rt.tools.list_tools(limit=200))

            # 9. ARES-harvested Local Knowledge Wiki HTTP + privacy_classify tool
            w_post = await client.post(
                "/v1/memory/wiki",
                json={"section": "concepts", "name": "Hybrid Routing", "content": "Local fallback keeps offline chat alive."},
            )
            assert w_post.status == 201
            w_search = await client.get("/v1/memory/wiki?q=offline+fallback")
            assert w_search.status == 200
            w_data = await w_search.json()
            assert w_data["count"] == 1 and w_data["results"][0]["name"] == "hybrid-routing"

            priv = rt.tools.execute("privacy_classify", {"content": "my bank account number is 999"})
            assert priv.ok and "sensitive" in priv.output and "false" in priv.output.lower()
    finally:
        rt.close()
