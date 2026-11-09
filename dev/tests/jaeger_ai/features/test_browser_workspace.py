"""Browser isolation and authorization on the real Gateway route stack."""
from pathlib import Path
import os

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.mark.asyncio
async def test_browser_session_authorization_precedes_worker_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    gw = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "sessions.sqlite3"))
    gw.app.on_startup.clear()
    gw.store.ensure_session("owner-browser")
    async with TestClient(TestServer(gw.app)) as client:
        path = "/v1/sessions/owner-browser/browser/action"
        assert (await client.post(path, json={"action": "status"})).status == 401
        assert (await client.post(path, json={"action": "status"}, headers=caller_auth.client_headers("ares"))).status == 403
        assert (await client.get("/v1/sessions/owner-browser/browser/cast?pageId=x", headers=caller_auth.client_headers("ares"))).status == 403
        assert (await client.post("/v1/sessions/missing/browser/action", json={"action": "status"}, headers=caller_auth.client_headers("webui"))).status == 404
        assert not gw.browser_runtime.workers
        response = await client.post(path, json={"action": "status"}, headers=caller_auth.client_headers("webui"))
        assert response.status == 503
        assert "runtime is missing" in (await response.json())["error"]


def test_interactive_stream_requires_turn_scope():
    assert caller_auth.required_scope("GET", "/v1/sessions/{id}/browser/cast") == "turn"
    assert caller_auth.required_scope("POST", "/v1/sessions/{id}/browser/action") == "turn"


def test_agent_browser_uses_admitted_session_and_existing_transport(monkeypatch):
    from jaeger_agent.tools import browser_shared
    seen = []
    monkeypatch.setattr(browser_shared, "_request_json", lambda method, path, body, timeout: (seen.append((method, path, body)) or (200, {"pages": [], "active": "tab"})))
    result = browser_shared.shared_browser({"session_id": "owned:session"}, "open", {"url": "https://example.com", "session_id": "other"})
    assert result["ok"]
    assert seen[0][1] == "/v1/sessions/owned%3Asession/browser/action"
    assert "session_id" not in seen[0][2]
    assert seen[0][2]["action"] == "navigate"


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("JAEGER_TEST_BROWSER_BUNDLE"), reason="Explicit built browser bundle required")
async def test_real_gateway_browser_keeps_selected_page_and_profiles_isolated(tmp_path, monkeypatch):
    from aiohttp import web, WSMsgType
    bundle = Path(os.environ["JAEGER_TEST_BROWSER_BUNDLE"])
    monkeypatch.setenv("JAEGER_HOME", str(tmp_path))
    monkeypatch.setenv("JAEGER_BROWSER_BUNDLE", str(bundle))
    gw = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / "sessions.sqlite3"))
    gw.app.on_startup.clear()
    gw.store.ensure_session("browser-one")
    gw.store.ensure_session("browser-two")
    async def fixture(_):
        return web.Response(text='<title>Shared browser proof</title><button id="count" onclick="this.textContent=Number(this.textContent)+1">0</button>', content_type="text/html")
    fixture_app = web.Application()
    fixture_app.router.add_get('/browser-fixture', fixture)
    headers = caller_auth.client_headers("webui")
    async with TestServer(fixture_app) as fixture_server, TestClient(TestServer(gw.app)) as client:
        async def act(sid, **body):
            response = await client.post(f"/v1/sessions/{sid}/browser/action", json=body, headers=headers)
            data = await response.json()
            assert response.status == 200, data
            return data
        first = await act("browser-one", action="navigate", url=str(fixture_server.make_url('/browser-fixture')), snapshot=True)
        assert first["title"] == "Shared browser proof"
        clicked = await act("browser-one", action="click", element=0, snapshot=True)
        assert clicked["elements"][0]["text"] == "1"
        second = await act("browser-two", action="status")
        assert second["active"] != first["active"]
        assert not any(p["url"].endswith('/browser-fixture') for p in second["pages"])
        assert (await act("browser-one", action="snapshot"))["elements"][0]["text"] == "1"
        viewer = await client.get(f"/v1/sessions/browser-one/browser/viewer?pageId={first['active']}", headers=headers)
        html = await viewer.text()
        assert viewer.status == 200
        assert 'location.host' in html and '/v1/sessions/browser-one/browser/cast' in html
        await act("browser-one", action="viewport", width=389, height=545)
        async with client.ws_connect(f"/v1/sessions/browser-one/browser/cast?pageId={first['active']}&format=binary", headers=headers) as ws:
            for _ in range(10):
                message = await ws.receive(timeout=10)
                if message.type == WSMsgType.BINARY:
                    assert len(message.data) > 100
                    actual = (await act("browser-one", action="snapshot"))["viewport"]
                    assert (actual["width"], actual["height"]) == (389, 545)
                    break
            else:
                pytest.fail("No rendered browser frame")
        workers = list(gw.browser_runtime.workers.values())
    assert all(w.process.returncode is not None for w in workers)
