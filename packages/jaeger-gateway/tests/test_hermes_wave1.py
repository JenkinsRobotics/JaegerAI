"""Wave 1 Hermes-Superset integration tests: self-evolving skills, parallel subagents,
FTS5 cross-session search, memory listing, recurring schedule proposals, and channel ingest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_gateway.runtime import ModularGatewayRuntime
from jaeger_gateway.store import MAIN_CHAT_SESSION_ID
from jaeger_models import ReplayModel


def test_self_evolving_workspace_skills_save_search_load_update(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        v1 = (
            "---\n"
            "name: deploy-check\n"
            "description: Verify local build artifacts before restarting the gateway\n"
            "---\n\n"
            "# Deploy Check\n\n"
            "1. Run the verification suite.\n"
            "2. Confirm health endpoint returns ok.\n"
        )
        res_save = runtime.tools.execute("save_workspace_skill", {"name": "deploy-check", "markdown": v1})
        assert res_save.ok, res_save.error

        # Duplicate save must fail closed (never silently overwrite).
        dup = runtime.tools.execute("save_workspace_skill", {"name": "deploy-check", "markdown": v1})
        assert not dup.ok

        # Search and load find the saved skill.
        found = runtime.tools.execute("search_workspace_skills", {"query": "deploy build artifacts"})
        assert found.ok
        results = json.loads(found.output)["results"]
        assert any(r["name"] == "deploy-check" for r in results)

        loaded = runtime.tools.execute("load_workspace_skill", {"name": "deploy-check"})
        assert loaded.ok
        assert "Confirm health endpoint" in json.loads(loaded.output)["procedure_data"]

        # Evolve the existing skill safely via update_workspace_skill.
        v2 = (
            "---\n"
            "name: deploy-check\n"
            "description: Verify local build artifacts and editable packages before restart\n"
            "---\n\n"
            "# Deploy Check v2\n\n"
            "1. Confirm editable package imports.\n"
            "2. Run the verification suite.\n"
            "3. Confirm health endpoint returns ok.\n"
        )
        res_upd = runtime.tools.execute("update_workspace_skill", {"name": "deploy-check", "markdown": v2})
        assert res_upd.ok, res_upd.error

        loaded2 = runtime.tools.execute("load_workspace_skill", {"name": "deploy-check"})
        assert loaded2.ok
        assert "Confirm editable package imports" in json.loads(loaded2.output)["procedure_data"]
    finally:
        runtime.close()


def test_parallel_subagent_delegation_and_estop_gate(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        runtime.model = ReplayModel([
            {"content": "Subagent A verified alpha."},
            {"content": "Subagent B verified beta."},
        ])
        # Synchronous delegation (wait=True)
        res_a = runtime.tools.execute(
            "delegate_task",
            {"task": "Check alpha", "role": "researcher", "read_only": True, "wait": True},
        )
        assert res_a.ok, res_a.error
        body_a = json.loads(res_a.output)
        assert body_a["status"] == "completed"
        assert body_a["verdict"] == "complete"
        assert "alpha" in body_a["content"]

        # Background delegation (wait=False) + delegate_status(wait=True)
        res_b = runtime.tools.execute(
            "delegate_task",
            {"task": "Check beta", "role": "auditor", "read_only": True, "wait": False},
        )
        assert res_b.ok, res_b.error
        aid_b = json.loads(res_b.output)["agent_id"]

        status_b = runtime.tools.execute("delegate_status", {"agent_id": aid_b, "wait": True})
        assert status_b.ok, status_b.error
        assert "beta" in json.loads(status_b.output)["content"]

        # E-Stop must block spawning new subagents fail-closed.
        runtime.governor.trigger_estop("test")
        blocked = runtime.tools.execute("delegate_task", {"task": "Should not run"})
        assert not blocked.ok
        err = (blocked.error or "").lower()
        assert "emergency stop" in err or "e-stop" in err
    finally:
        runtime.close()


def test_fts5_session_search_and_memory_list(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        s1 = runtime.store.main_chat_session()["session_id"]
        s2 = runtime.store.create_session(title="Episode Planning")["session_id"]
        runtime.store.append_message(s1, "user", "Let's configure the Insta360 gimbal privacy shutter.")
        runtime.store.append_message(s2, "assistant", "Episode 01 Awakening trailer uses an OTIO timeline.")

        search = runtime.tools.execute("session_search", {"query": "OTIO timeline"})
        assert search.ok, search.error
        hits = json.loads(search.output)["results"]
        assert len(hits) == 1
        assert hits[0]["session_id"] == s2
        assert "OTIO" in hits[0]["content"]

        # External channel sessions are excluded from agent session_search by default.
        runtime.store.ingest_channel_message("telegram", "thr-1", "m-1", "ext-user", "secret OTIO timeline ping")
        search2 = runtime.tools.execute("session_search", {"query": "OTIO timeline"})
        hits2 = json.loads(search2.output)["results"]
        assert all(h["session_id"] == s2 for h in hits2)

        # memory_list returns stored facts filtered by keyword.
        runtime.memory.remember("trailer_cut", "5-7 minute extended cut", subject="owner")
        runtime.memory.remember("rack_pc_ip", "10.0.0.42", subject="owner")
        mem_res = runtime.tools.execute("memory_list", {"subject": "owner", "query": "trailer"})
        assert mem_res.ok, mem_res.error
        facts = json.loads(mem_res.output)["facts"]
        assert len(facts) == 1 and facts[0]["key"] == "trailer_cut"
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_schedule_proposal_approval_and_chat_search_route(tmp_path: Path) -> None:
    runtime = ModularGatewayRuntime(state_dir=tmp_path / "state", workspace=tmp_path / "ws")
    try:
        runtime.store.main_chat_session()
        runtime.store.append_message(MAIN_CHAT_SESSION_ID, "user", "Remember the Voyager Minecraft bridge setup.")
        proposal = runtime.store.propose_scheduled_job(
            MAIN_CHAT_SESSION_ID, prompt="Morning digest", due_at=2_000_000_000.0, interval_s=3600.0,
        )
        aid = proposal["approval_id"]

        app = runtime.build_app(serve_ui=False)
        async with TestClient(TestServer(app)) as client:
            # FTS5 chat search route
            r_search = await client.get("/v1/chat/search?q=Voyager")
            assert r_search.status == 200
            data_s = await r_search.json()
            assert data_s["count"] >= 1 and "Voyager" in data_s["results"][0]["content"]

            # Approve schedule proposal -> creates recurring pending job
            r_app = await client.post(f"/v1/approvals/{aid}/resolve", json={"decision": "approve"})
            assert r_app.status == 200
            resolved = (await r_app.json())["approval"]
            assert resolved["status"] == "approved"
            assert resolved["job_id"] == f"job_{aid}"

            job = runtime.store.get_scheduled_job(resolved["job_id"])
            assert job is not None and job["status"] == "pending" and job["interval_s"] == 3600.0
    finally:
        runtime.close()
