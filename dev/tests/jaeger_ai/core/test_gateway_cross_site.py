"""A web page must not be able to drive the Gateway.

Live defect (2026-09-21 audit): a ``text/plain`` POST carrying
``Origin: https://evil.example`` created a session (201) and started an agent
turn (200). Browsers send such requests without a CORS preflight, so any page
the operator opened could run Jaeger. No endpoint is authenticated; loopback
was the only boundary.

Integration test against the real aiohttp app and middleware.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest_asyncio.fixture
async def client(tmp_path):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "xsite.sqlite3"))
    gateway.app.on_startup.clear()
    async with TestClient(TestServer(gateway.app)) as c:
        yield c


FORGED = '{"session_id": "forged", "title": "x"}'


@pytest.mark.asyncio
async def test_cross_origin_text_plain_post_is_refused(client):
    resp = await client.post(
        "/v1/sessions", data=FORGED,
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_cross_site_fetch_metadata_is_refused(client):
    resp = await client.post("/v1/sessions", data=FORGED, headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status == 403


@pytest.mark.asyncio
async def test_rebound_host_is_refused(client):
    resp = await client.get("/v1/approvals", headers={"Host": "evil.example:8810"})
    assert resp.status == 421


@pytest.mark.asyncio
async def test_real_clients_send_no_origin_and_still_work(client):
    resp = await client.post("/v1/sessions", json={"session_id": "real", "title": "x"})
    assert resp.status == 201
    assert (await client.get("/v1/sessions/real")).status == 200


@pytest.mark.asyncio
async def test_same_origin_loopback_is_allowed(client):
    origin = f"http://127.0.0.1:{client.server.port}"
    resp = await client.get("/v1/approvals", headers={"Origin": origin})
    assert resp.status == 200
