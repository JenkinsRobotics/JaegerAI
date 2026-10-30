"""Tests for POST /v1/app-reset (archive-first bulk history delete + optional memory wipe).

Safety contract under test:
  * auth required (401 without a token; admin scope)
  * archive happens BEFORE any deletion (archive file exists with content even
    if deletion then fails)
  * all sessions deleted through the store (children cascade)
  * body must be a JSON object; wipe_memory must be boolean true to trigger
  * memory wipe only touches the instance memory dir contents — identity,
    config, credentials, tokens are never listed as cleared
"""
from __future__ import annotations

import sqlite3

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def H(caller: str) -> dict[str, str]:
    headers = caller_auth.client_headers(caller)
    assert headers, f"test token for {caller} missing"
    return headers


@pytest_asyncio.fixture
async def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JAEGER_INSTANCE_DIR", str(tmp_path / "state" / "instance"))
    store = GatewaySessionStore(tmp_path / "reset.sqlite3")
    gateway = JaegerGatewayApp(store=store)
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app)) as client:
        client.gateway = gateway
        yield client


def _seed(client, n: int = 3) -> list[str]:
    ids = []
    for i in range(n):
        session = client.gateway.store.ensure_session(f"reset-{i}", title=f"Reset {i}")
        ids.append(session["session_id"])
    return ids


@pytest.mark.asyncio
async def test_reset_requires_auth(gw):
    resp = await gw.post("/v1/app-reset", json={})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_reset_deletes_all_sessions_and_archives_first(gw, tmp_path):
    ids = _seed(gw, 3)
    resp = await gw.post("/v1/app-reset", headers=H("webui"), json={})
    assert resp.status == 200
    body = await resp.json()
    assert body["reset"] is True
    assert body["deleted_sessions"] == 3
    assert body["failed_sessions"] == []
    # Archive exists and holds the seeded rows.
    archive = body["archive"]
    assert archive and archive.endswith(".sqlite3")
    conn = sqlite3.connect(archive)
    try:
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        conn.close()
    assert count == 3
    # Live store is empty afterwards.
    assert [s["session_id"] for s in gw.gateway.store.list_sessions()] == []
    # Memory wipe not requested → memory_cleared empty.
    assert body["memory_cleared"] == []


@pytest.mark.asyncio
async def test_reset_rejects_non_object_body(gw):
    resp = await gw.post("/v1/app-reset", headers=H("webui"), json=[1, 2])
    assert resp.status == 400


@pytest.mark.asyncio
async def test_memory_wipe_clears_instance_memory_contents_only(gw, tmp_path):
    memory_dir = tmp_path / "state" / "instance" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "state.db").write_bytes(b"facts")
    (memory_dir / "agents").mkdir()
    (memory_dir / "agents" / "NOTES.md").write_text("notes", encoding="utf-8")
    (memory_dir / "entity_identity.json").write_text("{}", encoding="utf-8")
    # Siblings that must survive:
    identity = tmp_path / "state" / "instance" / "identity.yaml"
    identity.write_text("name: test\n", encoding="utf-8")
    creds = tmp_path / "state" / "instance" / "credentials"
    creds.mkdir()
    (creds / "key.txt").write_text("secret", encoding="utf-8")

    resp = await gw.post("/v1/app-reset", headers=H("webui"), json={"wipe_memory": True})
    assert resp.status == 200
    body = await resp.json()
    assert set(body["memory_cleared"]) == {"state.db", "agents", "entity_identity.json"}
    assert body["memory_failed"] == []
    # Nothing outside memory/ was touched.
    assert identity.read_text(encoding="utf-8") == "name: test\n"
    assert (creds / "key.txt").read_text(encoding="utf-8") == "secret"


@pytest.mark.asyncio
async def test_reset_is_repeatable_when_empty(gw):
    first = await gw.post("/v1/app-reset", headers=H("webui"), json={})
    assert first.status == 200
    second = await gw.post("/v1/app-reset", headers=H("webui"), json={})
    assert second.status == 200
    body = await second.json()
    assert body["deleted_sessions"] == 0