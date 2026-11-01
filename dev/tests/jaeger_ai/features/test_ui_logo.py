"""Shared Jaeger logo choice: store, SVG sanitizer and /v1/ui/logo routes (J-085)."""
import asyncio
import base64
import types

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.features.ui_layout.logo import DEFAULT, check_custom, load, register, sanitize_svg, save


def test_store_defaults_and_builtins(tmp_path):
    p = tmp_path / "logo.json"
    assert load(p)["logo"] == DEFAULT
    assert save("j", path=p)["logo"] == "j"
    assert load(p)["logo"] == "j"
    with pytest.raises(ValueError):
        save("nope", path=p)


def test_sanitizer_strips_active_content():
    bad = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><script>alert(2)</script>' \
          b'<foreignObject><div/></foreignObject><a href="javascript:x"><path d="M0 0"/></a>' \
          b'<path d="M1 1" onclick="x" fill="url(http://evil/x)" style="fill:red"/><use href="https://evil/#a"/></svg>'
    out = sanitize_svg(bad).decode()
    for s in ("onload", "script", "foreignObject", "javascript", "onclick", "evil", "<a"):
        assert s not in out
    assert 'd="M1 1"' in out and "fill:red" in out
    with pytest.raises(ValueError):
        sanitize_svg(b'<!DOCTYPE x [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg"/>')
    with pytest.raises(ValueError):
        sanitize_svg(b"<html/>")


def test_raster_magic_and_size():
    assert check_custom("image/png", b"\x89PNG\r\n\x1a\nxx")
    with pytest.raises(ValueError):
        check_custom("image/png", b"GIF89a")
    with pytest.raises(ValueError):
        check_custom("image/png", b"\x89PNG\r\n\x1a\n" + b"0" * 300_000)


def test_routes_round_trip_custom(tmp_path):
    async def run():
        events = []
        gw = types.SimpleNamespace(app=web.Application(), event_bus=types.SimpleNamespace(publish=lambda *a: events.append(a)))
        register(gw, tmp_path / "logo.json")
        async with TestClient(TestServer(gw.app)) as c:
            assert (await (await c.get("/v1/ui/logo")).json())["logo"] == DEFAULT
            r = await c.post("/v1/ui/logo", json={"logo": "wordmark"})
            assert r.status == 200
            svg = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"><script/><circle r="4"/></svg>').decode()
            r = await c.post("/v1/ui/logo", json={"logo": "custom", "custom": {"mime": "image/svg+xml", "data_base64": svg}})
            assert r.status == 200
            got = await (await c.get("/v1/ui/logo")).json()
            assert got["logo"] == "custom"
            decoded = base64.b64decode(got["custom"]["data_url"].split(",", 1)[1])
            assert b"script" not in decoded and b"circle" in decoded
            assert (await c.post("/v1/ui/logo", json={"logo": "x"})).status == 400
            assert (await c.post("/v1/ui/logo", json={"logo": "j", "extra": 1})).status == 400
        assert events and events[0][1] == "ui.logo"
    asyncio.run(run())


def test_webui_passthrough_allows_logo():
    from jaeger_ai.features.webui.api.jaeger_sessions import GATEWAY_PASSTHROUGH
    assert any("POST" in m and rx.match("/v1/ui/logo") for m, rx in GATEWAY_PASSTHROUGH)
