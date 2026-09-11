"""Focused tests for AgentRegistry + gateway /v1/agents first cut."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import AioHTTPTestCase

from jaeger_ai.core.agent_registry import (
    AgentKind,
    AgentRegistry,
    is_native,
    is_third_party,
)
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.features.webui.service.profile_layout import library_model


def test_create_list_native_and_third_party(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    registry = AgentRegistry(tmp_path)

    native = registry.create_agent("lilith", display_name="Lilith", make_active=True)
    assert native.kind is AgentKind.NATIVE
    assert native.id == "native:lilith"
    assert (tmp_path / "instances" / "lilith" / "identity.yaml").is_file()
    assert (tmp_path / "active_instance").read_text(encoding="utf-8").strip() == "lilith"

    third = registry.register_third_party(
        "custom-bot",
        display_name="Custom Bot",
        adapter="custom-bot",
        endpoint="http://127.0.0.1:9999",
        port=9999,
    )
    assert third.kind is AgentKind.THIRD_PARTY
    assert third.id == "tp:custom-bot"

    agents = registry.list_agents()
    kinds = {a.kind for a in agents}
    assert AgentKind.NATIVE in kinds
    assert AgentKind.THIRD_PARTY in kinds
    # Built-ins always present.
    names = {a.name for a in agents}
    assert "hermes" in names
    assert "openclaw" in names
    assert "roundtable" in names
    assert "lilith" in names

    native_only = registry.list_agents(kind=AgentKind.NATIVE)
    assert all(is_native(a) for a in native_only)
    third_only = registry.list_agents(kind="third_party")
    assert all(is_third_party(a) for a in third_only)

    catalog = registry.to_catalog()
    assert catalog["fundamentals_fee_gated"] is False
    assert catalog["persistence_spine"] == "jaeger_gateway"
    assert catalog["counts"]["jaeger_native"] >= 1
    assert catalog["counts"]["third_party"] >= 3


def test_fundamentals_never_fee_gated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    registry = AgentRegistry(tmp_path)
    registry.create_agent("alpha")
    # Poison persisted state with a fee gate — load must strip it.
    path = registry.path
    raw = json.loads(path.read_text(encoding="utf-8"))
    for entry in raw["agents"].values():
        entry["fundamentals_gated"] = True
        entry["switchable"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")

    reloaded = AgentRegistry(tmp_path)
    for agent in reloaded.list_agents():
        assert agent.fundamentals_gated is False
        assert agent.switchable is True
        payload = agent.to_dict()
        assert payload["fundamentals_gated"] is False
        assert payload["switchable"] is True

    activated = reloaded.set_active("native:alpha")
    assert activated.active is True


def test_library_model_includes_support_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    AgentRegistry(tmp_path).create_agent("nova")
    model = library_model()
    assert model["mode"] == "single_library"
    assert model["support_model"]["jaeger_native"] is True
    assert model["support_model"]["third_party"] is True
    assert model["support_model"]["fundamentals_fee_gated"] is False
    assert "agents" in model
    assert model["agents"]["counts"]["jaeger_native"] >= 1


class TestGatewayAgentsAPI(AioHTTPTestCase):
    async def get_application(self):
        import tempfile

        self.state_root = Path(tempfile.mkdtemp())
        self.db_path = self.state_root / "sessions.sqlite3"
        # Point registry at isolated state for this test case.
        import os

        os.environ["JAEGER_STATE_DIR"] = str(self.state_root)
        self.temp_store = GatewaySessionStore(self.db_path)
        self.gateway_app = JaegerGatewayApp(store=self.temp_store)
        return self.gateway_app.app

    async def tearDownAsync(self):
        import os
        import shutil

        os.environ.pop("JAEGER_STATE_DIR", None)
        if hasattr(self, "state_root") and self.state_root.exists():
            shutil.rmtree(self.state_root, ignore_errors=True)
        await super().tearDownAsync()

    async def test_agents_catalog_create_and_activate(self):
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        health = await resp.json()
        assert health["agents_api"] == "/v1/agents"
        assert health["fundamentals_fee_gated"] is False

        resp = await self.client.request("GET", "/v1/agents")
        assert resp.status == 200
        catalog = await resp.json()
        assert catalog["fundamentals_fee_gated"] is False
        assert len(catalog["third_party"]) >= 3

        resp = await self.client.request(
            "POST",
            "/v1/agents",
            json={"name": "aurora", "kind": "jaeger_native", "display_name": "Aurora"},
        )
        assert resp.status == 201
        created = await resp.json()
        assert created["id"] == "native:aurora"
        assert created["kind"] == "jaeger_native"
        assert created["fundamentals_gated"] is False

        resp = await self.client.request("GET", "/v1/agents/native:aurora")
        assert resp.status == 200
        fetched = await resp.json()
        assert fetched["name"] == "aurora"

        resp = await self.client.request("POST", "/v1/agents/native:aurora/activate")
        assert resp.status == 200
        activated = await resp.json()
        assert activated["active"] is True

        resp = await self.client.request(
            "POST",
            "/v1/agents",
            json={
                "name": "ext",
                "kind": "third_party",
                "adapter": "ext",
                "endpoint": "http://127.0.0.1:8777",
                "port": 8777,
            },
        )
        assert resp.status == 201
        tp = await resp.json()
        assert tp["kind"] == "third_party"


def test_standing_specialists_seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    registry = AgentRegistry(tmp_path)
    agents = registry.list_agents()
    by_id = {a.id: a for a in agents}
    assert "native:jaeger" in by_id
    assert by_id["native:jaeger"].display_name == "Assistant"
    assert by_id["native:jaeger"].metadata.get("role") == "lead"
    for name in ("surfaces", "gateway", "everyday"):
        aid = f"native:{name}"
        assert aid in by_id, aid
        assert by_id[aid].metadata.get("specialist") is True
        assert by_id[aid].metadata.get("role") == name
    catalog = registry.to_catalog()
    assert catalog["model"] == "grok_bot_shape"
    assert catalog["counts"]["jaeger_native"] >= 4


class TestGatewayHandoffAPI(AioHTTPTestCase):
    async def get_application(self):
        import os
        import tempfile

        self.state_root = Path(tempfile.mkdtemp())
        os.environ["JAEGER_STATE_DIR"] = str(self.state_root)
        self.temp_store = GatewaySessionStore(self.state_root / "sessions.sqlite3")
        self.gateway_app = JaegerGatewayApp(store=self.temp_store)
        return self.gateway_app.app

    async def tearDownAsync(self):
        import os
        import shutil

        os.environ.pop("JAEGER_STATE_DIR", None)
        if hasattr(self, "state_root") and self.state_root.exists():
            shutil.rmtree(self.state_root, ignore_errors=True)
        await super().tearDownAsync()

    async def test_handoff_creates_approval_and_resolves(self):
        # Ensure specialists exist via catalog
        resp = await self.client.request("GET", "/v1/agents")
        assert resp.status == 200
        catalog = await resp.json()
        ids = {a["id"] for a in catalog["agents"]}
        assert "native:surfaces" in ids

        resp = await self.client.request(
            "POST",
            "/v1/agents/native:surfaces/handoff",
            json={
                "task": "Align WebUI agents chrome with Mac",
                "from_agent_id": "native:jaeger",
                "require_approval": True,
            },
        )
        assert resp.status == 202
        handoff = await resp.json()
        assert handoff["status"] == "pending_approval"
        assert handoff["to_agent_id"] == "native:surfaces"
        approval_id = handoff["approval_id"]
        assert approval_id

        resp = await self.client.request(
            "POST",
            f"/v1/approvals/{approval_id}",
            json={"approved": True},
        )
        assert resp.status == 200
        resolved = await resp.json()
        assert resolved["approved"] is True
        assert resolved["handoff"]["status"] == "approved"

        resp = await self.client.request("GET", "/v1/handoffs")
        assert resp.status == 200
        listing = await resp.json()
        assert listing["count"] >= 1

    async def test_handoff_missing_agent_clean_404(self):
        resp = await self.client.request(
            "POST",
            "/v1/agents/native:does-not-exist/handoff",
            json={"task": "x", "require_approval": False},
        )
        assert resp.status == 404
        body = await resp.json()
        assert "error" in body

    async def test_resolve_unknown_approval_clean_404(self):
        resp = await self.client.request(
            "POST",
            "/v1/approvals/approval_nonexistent_xyz",
            json={"approved": True},
        )
        assert resp.status == 404
        body = await resp.json()
        assert body.get("error") == "Approval not found"

    async def test_resolve_approval_twice_clean_404(self):
        """Second resolve of the same approval_id → clean 404 (not corrupt)."""
        resp = await self.client.request(
            "POST",
            "/v1/agents/native:gateway/handoff",
            json={
                "task": "double resolve",
                "from_agent_id": "native:jaeger",
                "require_approval": True,
            },
        )
        assert resp.status == 202
        approval_id = (await resp.json())["approval_id"]
        assert approval_id

        resp = await self.client.request(
            "POST",
            f"/v1/approvals/{approval_id}",
            json={"approved": True},
        )
        assert resp.status == 200
        first = await resp.json()
        assert first["resolved"] is True
        assert first["approved"] is True

        resp = await self.client.request(
            "POST",
            f"/v1/approvals/{approval_id}",
            json={"approved": False},
        )
        assert resp.status == 404
        body = await resp.json()
        assert body.get("error") == "Approval not found"


def test_role_defaults_and_catalog_lead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    # Seed a native jaeger instance so discovery marks it lead.
    (tmp_path / "instances" / "jaeger").mkdir(parents=True)
    (tmp_path / "instances" / "jaeger" / "identity.yaml").write_text(
        "name: Assistant\n", encoding="utf-8"
    )
    (tmp_path / "instances" / "default").mkdir(parents=True)
    registry = AgentRegistry(tmp_path)
    agents = {a.id: a for a in registry.list_agents()}
    assert agents["native:jaeger"].role.value == "lead"
    assert agents["native:default"].role.value in {"runtime", "specialist"}
    assert agents["tp:hermes"].role.value == "specialist"
    specialists = registry.list_agents(role="specialist")
    assert specialists
    assert all(a.role.value == "specialist" for a in specialists)
    catalog = registry.to_catalog()
    assert catalog["lead"]["id"] == "native:jaeger"
    assert catalog["lead"]["role"] == "lead"
    assert catalog["counts"]["specialist"] >= 1


class TestGatewaySessionHandoff(AioHTTPTestCase):
    async def get_application(self):
        import os
        import tempfile

        self.state_root = Path(tempfile.mkdtemp())
        os.environ["JAEGER_STATE_DIR"] = str(self.state_root)
        (self.state_root / "instances" / "jaeger").mkdir(parents=True)
        (self.state_root / "instances" / "jaeger" / "identity.yaml").write_text(
            "name: Assistant\n", encoding="utf-8"
        )
        self.temp_store = GatewaySessionStore(self.state_root / "sessions.sqlite3")
        self.gateway_app = JaegerGatewayApp(store=self.temp_store)
        return self.gateway_app.app

    async def tearDownAsync(self):
        import os
        import shutil

        os.environ.pop("JAEGER_STATE_DIR", None)
        if hasattr(self, "state_root") and self.state_root.exists():
            shutil.rmtree(self.state_root, ignore_errors=True)
        await super().tearDownAsync()

    async def test_session_handoff_and_role_filter(self):
        resp = await self.client.request("GET", "/v1/agents")
        assert resp.status == 200
        catalog = await resp.json()
        assert catalog["lead"]["role"] == "lead"
        assert "specialists" in catalog

        resp = await self.client.request("GET", "/v1/agents?role=specialist")
        assert resp.status == 200
        filtered = await resp.json()
        assert filtered["role"] == "specialist"
        assert filtered["agents"]
        assert all(a["role"] == "specialist" for a in filtered["agents"])

        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={"session_id": "handoff-sess", "title": "Handoff", "profile": "jaeger"},
        )
        assert resp.status == 201

        to_id = filtered["agents"][0]["id"]
        resp = await self.client.request(
            "POST",
            "/v1/sessions/handoff-sess/handoff",
            json={"to_agent_id": to_id, "reason": "P6 probe", "keep_history": True},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["session_id"] == "handoff-sess"
        assert body["agent_id"] == to_id
        assert body["session"]["agent_id"] == to_id
        assert body["session"]["metadata"]["handoff_reason"] == "P6 probe"

        resp = await self.client.request(
            "POST",
            "/v1/sessions/missing/handoff",
            json={"to_agent_id": to_id},
        )
        assert resp.status == 404

    async def test_session_handoff_missing_agent_404(self):
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={"session_id": "miss-agent", "title": "x"},
        )
        assert resp.status == 201
        resp = await self.client.request(
            "POST",
            "/v1/sessions/miss-agent/handoff",
            json={"to_agent_id": "native:does-not-exist"},
        )
        assert resp.status == 404
        body = await resp.json()
        assert body.get("error") == "Agent not found"

    async def test_handoff_to_lead_and_specialist_allowed(self):
        resp = await self.client.request("GET", "/v1/agents")
        catalog = await resp.json()
        lead_id = catalog["lead"]["id"]
        assert catalog["lead"]["role"] == "lead"

        resp = await self.client.request("GET", "/v1/agents?role=lead")
        leads = await resp.json()
        assert all(a["role"] == "lead" for a in leads["agents"])
        assert any(a["id"] == lead_id for a in leads["agents"])

        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "lead-specialist",
                "title": "roles",
                "metadata": {"agent_id": lead_id},
            },
        )
        assert resp.status == 201

        resp = await self.client.request("GET", "/v1/agents?role=specialist")
        specs = await resp.json()
        specialist_id = next(
            a["id"] for a in specs["agents"] if a["id"] == "native:gateway"
        )

        resp = await self.client.request(
            "POST",
            "/v1/sessions/lead-specialist/handoff",
            json={"to_agent_id": specialist_id, "reason": "to specialist"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["agent_id"] == specialist_id
        assert body["previous_agent_id"] == lead_id

        resp = await self.client.request(
            "POST",
            "/v1/sessions/lead-specialist/handoff",
            json={"to_agent_id": lead_id, "reason": "back to lead"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["agent_id"] == lead_id
        assert body["previous_agent_id"] == specialist_id

        resp = await self.client.request("GET", "/v1/agents")
        catalog2 = await resp.json()
        assert catalog2["lead"]["id"] == lead_id
        assert catalog2["lead"]["role"] == "lead"

    async def test_double_handoff_chain_keeps_agent_id(self):
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "double-ho",
                "title": "chain",
                "metadata": {"agent_id": "native:jaeger"},
            },
        )
        assert resp.status == 201

        resp = await self.client.request(
            "POST",
            "/v1/sessions/double-ho/handoff",
            json={"to_agent_id": "native:gateway", "reason": "1"},
        )
        assert resp.status == 200
        assert (await resp.json())["agent_id"] == "native:gateway"

        resp = await self.client.request(
            "POST",
            "/v1/sessions/double-ho/handoff",
            json={"to_agent_id": "native:surfaces", "reason": "2"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["agent_id"] == "native:surfaces"
        assert body["previous_agent_id"] == "native:gateway"

        resp = await self.client.request("GET", "/v1/sessions/double-ho")
        sess = await resp.json()
        assert sess["agent_id"] == "native:surfaces"
        assert sess["metadata"]["agent_id"] == "native:surfaces"
        assert sess["metadata"]["previous_agent_id"] == "native:gateway"

    async def test_keep_history_false_clears_messages(self):
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={"session_id": "kh-clear", "title": "kh"},
        )
        assert resp.status == 201
        self.temp_store.append_message("kh-clear", "user", "hello")
        self.temp_store.append_message("kh-clear", "assistant", "hi")
        sess = self.temp_store.get_session("kh-clear")
        assert len(sess["messages"]) == 2

        resp = await self.client.request(
            "POST",
            "/v1/sessions/kh-clear/handoff",
            json={
                "to_agent_id": "native:gateway",
                "reason": "wipe",
                "keep_history": False,
            },
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["keep_history"] is False
        assert body["agent_id"] == "native:gateway"
        sess = self.temp_store.get_session("kh-clear")
        assert sess["messages"] == []
        assert sess["agent_id"] == "native:gateway"


    async def test_session_handoff_empty_to_agent_id_400(self):
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={"session_id": "empty-to", "title": "Empty"},
        )
        assert resp.status == 201
        resp = await self.client.request(
            "POST",
            "/v1/sessions/empty-to/handoff",
            json={"to_agent_id": "", "reason": "blank"},
        )
        assert resp.status == 400
        body = await resp.json()
        assert "to_agent_id" in body.get("error", "")

    async def test_get_session_includes_role_display_name_after_handoff(self):
        """Chrome polls GET /v1/sessions/{id} without SSE — need identity fields."""
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "get-enrich",
                "title": "Enrich",
                "metadata": {"agent_id": "native:jaeger"},
            },
        )
        assert resp.status == 201
        resp = await self.client.request(
            "POST",
            "/v1/sessions/get-enrich/handoff",
            json={"to_agent_id": "native:gateway", "reason": "chrome"},
        )
        assert resp.status == 200

        resp = await self.client.request("GET", "/v1/sessions/get-enrich")
        assert resp.status == 200
        sess = await resp.json()
        assert sess["agent_id"] == "native:gateway"
        assert sess["role"] == "specialist"
        assert sess["display_name"] == "Gateway"
        # agent_id must survive GET enrichment (no corruption)
        assert sess["metadata"]["agent_id"] == "native:gateway"

    async def test_concurrent_turn_while_running_409(self):
        """Second turn while status=running → clean 409; agent_id intact."""
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "conc-turn",
                "title": "Concurrent",
                "metadata": {"agent_id": "native:gateway"},
            },
        )
        assert resp.status == 201

        # Force running without waiting on Ollama
        self.temp_store.update_status("conc-turn", "running")

        resp = await self.client.request(
            "POST",
            "/v1/sessions/conc-turn/turns",
            json={"text": "second while running"},
        )
        assert resp.status == 409
        body = await resp.json()
        assert body.get("error") == "Turn already in progress"
        assert body.get("status") == "running"
        assert body.get("agent_id") == "native:gateway"

        sess = self.temp_store.get_session("conc-turn")
        assert sess["status"] == "running"
        assert sess["agent_id"] == "native:gateway"
        # No user message appended for the rejected turn
        assert sess["messages"] == []



def test_system_prompt_for_session_agent_specialist():
    """P6: handoff agent identity must drive the Ollama system prompt."""
    from jaeger_ai.core.agent_registry.types import AgentKind, AgentRecord, AgentRole
    from jaeger_ai.core.gateway.server import JaegerGatewayApp

    agent = AgentRecord(
        id="native:gateway",
        name="gateway",
        kind=AgentKind.NATIVE,
        display_name="Gateway",
        source="registry",
        role=AgentRole.SPECIALIST,
        metadata={
            "specialty": "gateway",
            "summary": "Spine health, agents catalog, sessions, and approvals on :8810.",
        },
    )
    prompt = JaegerGatewayApp._system_prompt_for_agent(agent)
    assert "You are Gateway." in prompt
    assert "gateway specialist" in prompt.lower()
    assert "SPECIALIST:Gateway" in prompt
    assert "You are Jaeger." not in prompt

    lead = AgentRecord(
        id="native:jaeger",
        name="jaeger",
        kind=AgentKind.NATIVE,
        display_name="Assistant",
        source="registry",
        role=AgentRole.LEAD,
        metadata={"specialty": "lead", "summary": "Lead assistant."},
    )
    lead_prompt = JaegerGatewayApp._system_prompt_for_agent(lead)
    assert "You are Assistant." in lead_prompt
    assert "lead assistant" in lead_prompt.lower()

    assert JaegerGatewayApp._system_prompt_for_agent(None).startswith("You are Jaeger.")


class TestGatewayTurnUsesSessionAgent(AioHTTPTestCase):
    """Live-turn path must resolve session agent_id into turn.finish fields."""

    async def get_application(self):
        import os
        import tempfile

        self.state_root = Path(tempfile.mkdtemp())
        os.environ["JAEGER_STATE_DIR"] = str(self.state_root)
        (self.state_root / "instances" / "jaeger").mkdir(parents=True)
        (self.state_root / "instances" / "jaeger" / "identity.yaml").write_text(
            "name: Assistant\n", encoding="utf-8"
        )
        (self.state_root / "instances" / "gateway").mkdir(parents=True)
        (self.state_root / "instances" / "gateway" / "identity.yaml").write_text(
            "name: Gateway\n", encoding="utf-8"
        )
        self.temp_store = GatewaySessionStore(self.state_root / "sessions.sqlite3")
        self.gateway_app = JaegerGatewayApp(store=self.temp_store)
        return self.gateway_app.app

    async def tearDownAsync(self):
        import os
        import shutil

        os.environ.pop("JAEGER_STATE_DIR", None)
        if hasattr(self, "state_root") and self.state_root.exists():
            shutil.rmtree(self.state_root, ignore_errors=True)
        await super().tearDownAsync()

    async def test_execute_turn_publishes_agent_on_finish(self):
        # Seed standing specialists via registry list (ensure_standing runs on get).
        resp = await self.client.request("GET", "/v1/agents?role=specialist")
        assert resp.status == 200
        filtered = await resp.json()
        gateway = next(a for a in filtered["agents"] if a["id"] == "native:gateway")

        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "p6-turn",
                "title": "P6",
                "metadata": {"agent_id": "native:jaeger"},
            },
        )
        assert resp.status == 201

        resp = await self.client.request(
            "POST",
            "/v1/sessions/p6-turn/handoff",
            json={
                "to_agent_id": gateway["id"],
                "reason": "P6 proof",
                "keep_history": True,
            },
        )
        assert resp.status == 200

        captured: dict = {}

        async def fake_chat(text: str, *, system_prompt: str | None = None) -> str:
            captured["system_prompt"] = system_prompt
            captured["text"] = text
            return "SPECIALIST:Gateway"

        self.gateway_app._ollama_chat = fake_chat  # type: ignore[method-assign]

        await self.gateway_app._execute_turn(
            "p6-turn", "turn-abc", "Reply with exactly: SPECIALIST:<your display name>"
        )

        assert "You are Gateway." in (captured.get("system_prompt") or "")
        assert "SPECIALIST:Gateway" in (captured.get("system_prompt") or "")

        session = self.temp_store.get_session("p6-turn")
        assert session is not None
        assert session["status"] == "idle"
        assert session["agent_id"] == "native:gateway"
        assert any(
            m["role"] == "assistant" and "SPECIALIST:Gateway" in m["content"]
            for m in session["messages"]
        )

        finishes = [
            e
            for e in self.gateway_app.event_bus.get_replay_events("p6-turn")
            if e.event == "turn.finish"
        ]
        assert finishes, "expected turn.finish event with agent fields"
        data = finishes[-1].data
        assert data.get("agent_id") == "native:gateway"
        assert data.get("display_name") == "Gateway"
        assert data.get("role") == "specialist"

    async def test_double_handoff_then_turn_identity(self):
        """After A→B→C handoffs, next turn.finish stamps C's identity."""
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "p6-double",
                "title": "double",
                "metadata": {"agent_id": "native:jaeger"},
            },
        )
        assert resp.status == 201

        for to_id, reason in (
            ("native:gateway", "1"),
            ("native:surfaces", "2"),
        ):
            resp = await self.client.request(
                "POST",
                "/v1/sessions/p6-double/handoff",
                json={"to_agent_id": to_id, "reason": reason, "keep_history": True},
            )
            assert resp.status == 200
            assert (await resp.json())["agent_id"] == to_id

        captured: dict = {}

        async def fake_chat(text: str, *, system_prompt: str | None = None) -> str:
            captured["system_prompt"] = system_prompt
            return "SPECIALIST:Surfaces"

        self.gateway_app._ollama_chat = fake_chat  # type: ignore[method-assign]

        await self.gateway_app._execute_turn(
            "p6-double",
            "turn-double",
            "Reply with exactly: SPECIALIST:<your display name>",
        )

        assert "You are Surfaces." in (captured.get("system_prompt") or "")
        finishes = [
            e
            for e in self.gateway_app.event_bus.get_replay_events("p6-double")
            if e.event == "turn.finish"
        ]
        assert finishes
        data = finishes[-1].data
        assert data.get("agent_id") == "native:surfaces"
        assert data.get("display_name") == "Surfaces"
        assert data.get("role") == "specialist"

    async def test_keep_history_false_then_turn_still_works(self):
        resp = await self.client.request(
            "POST",
            "/v1/sessions",
            json={
                "session_id": "p6-kh",
                "title": "kh",
                "metadata": {"agent_id": "native:jaeger"},
            },
        )
        assert resp.status == 201
        self.temp_store.append_message("p6-kh", "user", "prior")
        self.temp_store.append_message("p6-kh", "assistant", "prior-reply")

        resp = await self.client.request(
            "POST",
            "/v1/sessions/p6-kh/handoff",
            json={
                "to_agent_id": "native:gateway",
                "reason": "wipe",
                "keep_history": False,
            },
        )
        assert resp.status == 200
        assert self.temp_store.get_session("p6-kh")["messages"] == []

        async def fake_chat(text: str, *, system_prompt: str | None = None) -> str:
            return "ok-after-clear"

        self.gateway_app._ollama_chat = fake_chat  # type: ignore[method-assign]
        await self.gateway_app._execute_turn("p6-kh", "turn-kh", "ping")

        session = self.temp_store.get_session("p6-kh")
        assert session["status"] == "idle"
        assert session["agent_id"] == "native:gateway"
        assert any(
            m["role"] == "assistant" and m["content"] == "ok-after-clear"
            for m in session["messages"]
        )
        finishes = [
            e
            for e in self.gateway_app.event_bus.get_replay_events("p6-kh")
            if e.event == "turn.finish"
        ]
        data = finishes[-1].data
        assert data.get("agent_id") == "native:gateway"
        assert data.get("role") == "specialist"
        assert data.get("display_name") == "Gateway"
