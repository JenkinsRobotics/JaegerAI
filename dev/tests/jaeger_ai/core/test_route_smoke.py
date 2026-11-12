"""Smoke: every GET route on the gateway router answers without a 5xx against a temp store (no ~/.jaeger)."""
import importlib.util
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("smoke_routes", ROOT / "dev/scripts/smoke_routes.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_enumeration_covers_new_routes():
    routes = {r["route"]: r for r in smoke.enumerate_routes()}
    for r in ("/v1/activity", "/v1/approvals/inbox", "/v1/widgets", "/v1/machine/health", "/v1/robots",
              "/v1/automations/n8n/status", "/v1/research/youtube/progress", "/v1/push/vapid-public-key",
              "/v1/resources", "/v1/providers/cli"):
        assert r in routes and not routes[r]["skip"], r
    assert smoke.UNSAFE.search("/v1/robots/arm1/estop") and smoke.UNSAFE.search("/v1/widgets/actions")
    assert smoke.main(["--base", "http://example.com", "--list"]) == 2  # loopback only


@pytest.mark.asyncio
async def test_gateway_get_routes_no_5xx(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_SECRETS_DIR", str(tmp_path / "secrets"))
    g = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "gw.sqlite3"))
    routes = sorted({r.resource.canonical for r in g.app.router.routes() if r.method == "GET" and r.resource})
    bad = []
    async with TestClient(TestServer(g.app), headers=client_headers("webui")) as c:
        for route in routes:
            if smoke.UNSAFE.search(route) or smoke.STREAM.search(route):
                continue
            r = await c.get(smoke.concrete(route))
            if r.status >= 500 and r.status != 503:  # 503 = upstream not configured in a temp instance
                bad.append((route, r.status))
    assert len(routes) > 50
    assert bad == []


def test_gateway_only_404_on_webui_is_flagged_as_gap():
    assert smoke.classify(404, None, False, "gateway") == "GAP-webui"
    assert smoke.classify(404, None, False, "webui") == "NOT-MOUNTED"
    assert smoke.classify(404, None, True, "gateway") == "OK-404"
    assert smoke.classify(200, None, False, "gateway") == "OK"
