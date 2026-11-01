"""First-run record and Gateway contract for the selected instance."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance import first_boot


def test_skip_persists_and_migration_protects_existing(tmp_path):
    fresh = tmp_path / "fresh"
    assert first_boot.ensure_migrated(fresh) is first_boot.FirstBootStatus.NOT_STARTED
    assert first_boot.skip(fresh) is first_boot.FirstBootStatus.COMPLETED
    original = first_boot.snapshot(fresh)
    assert original["skipped_at"]
    assert first_boot.skip(fresh) is first_boot.FirstBootStatus.COMPLETED
    assert first_boot.snapshot(fresh) == original
    established = tmp_path / "established"
    established.mkdir()
    (established / "identity.yaml").write_text("name: established")
    assert first_boot.ensure_migrated(established) is first_boot.FirstBootStatus.COMPLETED
    assert first_boot.snapshot(established)["migrated"] is True
    assert "skipped_at" not in first_boot.snapshot(established)


def test_gateway_startup_reserves_fresh_before_memory_bind(tmp_path):
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_agent.memory import sqlite_store
    layout = InstanceLayout(root=tmp_path / "selected")
    assert first_boot.reserve_fresh_instance(layout) is first_boot.FirstBootStatus.NOT_STARTED
    try:
        sqlite_store.bind(layout)
        assert (layout.memory_dir / "state.db").is_file()
        assert first_boot.ensure_migrated(layout) is first_boot.FirstBootStatus.NOT_STARTED
    finally:
        sqlite_store.close()


@pytest.mark.asyncio
async def test_gateway_first_run_routes(tmp_path, monkeypatch):
    root = tmp_path / "selected"
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(root))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    with patch.object(gateway, "_first_run_mutation_allowed", return_value=True):
        async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
            fresh = await (await client.get("/v1/first-run")).json()
            assert fresh["status"] == "NOT_STARTED" and not fresh["completed"]
            assert (root / "memory" / "state.db").exists()
            assert first_boot.snapshot(root)["status"] == "NOT_STARTED"
            calls = []
            def complete(layout, body):
                calls.append(body)
                first_boot.record_model_selection(layout, body["awake_provider"], body["awake_model"])
                first_boot.skip(layout)
            with patch("jaeger_ai.core.instance.onboarding_setup.complete_setup", side_effect=complete):
                body = {"character_id": "lilith", "awake_provider": "ollama", "awake_model": "test"}
                first = await (await client.post("/v1/first-run/setup", json=body)).json()
                repeat = await (await client.post("/v1/first-run/setup", json=body)).json()
                assert first == repeat and len(calls) == 1
                assert first["completed"]
            assert (await client.post("/v1/first-run/skip")).status == 200
    other = tmp_path / "other"
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(other))
    with patch.object(gateway, "_first_run_mutation_allowed", return_value=True):
        async with TestClient(TestServer(gateway.app), headers=client_headers("webui")) as client:
            one = await (await client.post("/v1/first-run/skip")).json()
            two = await (await client.post("/v1/first-run/skip")).json()
            assert one == two and one["skipped"]


@pytest.mark.asyncio
async def test_gateway_first_run_refuses_unauthorized_and_nonlocal(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "selected"))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gateway.sqlite3"))
    async with TestClient(TestServer(gateway.app)) as client:
        assert (await client.post("/v1/first-run/skip")).status == 401
        assert (await client.get("/v1/first-run")).status == 401
        assert (await client.post("/v1/first-run/skip", headers=client_headers("ares"))).status == 403
    for remote in ("8.8.8.8", "100.64.0.1", "100.127.255.254", "not-an-ip"):
        request = SimpleNamespace(remote=remote, get=lambda key: SimpleNamespace(name="webui"))
        assert not gateway._first_run_mutation_allowed(request)
