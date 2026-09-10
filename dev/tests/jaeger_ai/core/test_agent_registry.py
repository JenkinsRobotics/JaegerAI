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
