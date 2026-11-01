"""Shared UI layout preset: store and /v1/ui/layout routes."""
import asyncio
import types

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.features.ui_layout.routes import DEFAULT, load, register, save


def test_store_defaults_and_rejects_unknown(tmp_path):
    p = tmp_path / "layout.json"
    assert load(p)["preset"] == DEFAULT
    assert save("arc", p)["preset"] == "arc"
    assert load(p)["preset"] == "arc"
    p.write_text("{bad")
    assert load(p)["preset"] == DEFAULT
    try:
        save("nope", p)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown preset accepted")


def test_routes_round_trip(tmp_path):
    async def run():
        events = []
        gw = types.SimpleNamespace(app=web.Application(), event_bus=types.SimpleNamespace(publish=lambda *a: events.append(a)))
        register(gw, tmp_path / "layout.json")
        async with TestClient(TestServer(gw.app)) as c:
            r = await c.get("/v1/ui/layout")
            assert (await r.json())["preset"] == "glass"
            r = await c.post("/v1/ui/layout", json={"preset": "linear"})
            assert r.status == 200 and (await r.json())["preset"] == "linear"
            r = await c.post("/v1/ui/layout", json={"preset": "x"})
            assert r.status == 400
            r = await c.post("/v1/ui/layout", json={"preset": "dia", "extra": 1})
            assert r.status == 400
            assert (await (await c.get("/v1/ui/layout")).json())["preset"] == "linear"
        assert events and events[0][1] == "ui.layout"
    asyncio.run(run())


def test_webui_passthrough_allows_layout():
    from jaeger_ai.features.webui.api.jaeger_sessions import GATEWAY_PASSTHROUGH
    assert any("GET" in m and rx.match("/v1/ui/layout") for m, rx in GATEWAY_PASSTHROUGH)
    assert any("POST" in m and rx.match("/v1/ui/layout") for m, rx in GATEWAY_PASSTHROUGH)
