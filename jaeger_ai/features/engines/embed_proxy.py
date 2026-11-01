"""Loopback-only reverse proxy that lets Jaeger embed Hermes's and OpenClaw's own UIs.

Both upstream UIs refuse to be framed (OpenClaw sends ``X-Frame-Options: DENY`` and
``frame-ancestors 'none'``). This proxy listens on 127.0.0.1 only, forwards HTTP and
WebSocket traffic to the engine's loopback UI, and swaps the frame headers for a
``frame-ancestors`` list of Jaeger's own origins. It refuses any non-loopback peer.

  127.0.0.1:8797 -> OpenClaw Control UI (127.0.0.1:18789)
  127.0.0.1:8798 -> Hermes dashboard     (127.0.0.1:9119)

``/__jaeger/start`` on the OpenClaw port redirects to ``/#token=…`` (URL fragment, never
logged or sent upstream) using Jaeger's host OpenClaw gateway token file.

Run: python -m jaeger_ai.features.engines.embed_proxy
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

from aiohttp import ClientSession, WSMsgType, web

HOME = Path.home()
JAEGER_ORIGINS = ("http://127.0.0.1:8790", "http://localhost:8790",
                  "https://matthews-mac-studio.tail80f206.ts.net:8443")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailers", "transfer-encoding", "upgrade", "content-length", "content-encoding"}
STRIP_RESP = HOP | {"x-frame-options", "content-security-policy"}


@dataclass(frozen=True)
class Target:
    name: str
    listen: int
    upstream: int
    token_file: Path | None = None


TARGETS = (
    Target("openclaw", int(os.environ.get("JAEGER_EMBED_OPENCLAW_PORT", "8797")),
           int(os.environ.get("JAEGER_OPENCLAW_UI_PORT", "18789")),
           Path(os.environ.get("JAEGER_OPENCLAW_STATE", HOME / ".jaeger/openclaw-host")) / "gateway.token"),
    Target("hermes", int(os.environ.get("JAEGER_EMBED_HERMES_PORT", "8798")),
           int(os.environ.get("JAEGER_HERMES_DASHBOARD_PORT", "9119"))),
)


def is_loopback(remote: str | None) -> bool:
    try:
        return ipaddress.ip_address((remote or "").split("%")[0]).is_loopback
    except ValueError:
        return False


def frame_policy() -> str:
    return "frame-ancestors 'self' " + " ".join(JAEGER_ORIGINS)


def rewrite_csp(csp: str | None) -> str:
    """Keep the engine's own CSP; only replace its frame-ancestors directive."""
    parts = [d.strip() for d in (csp or "").split(";") if d.strip()]
    kept = [d for d in parts if not d.lower().startswith("frame-ancestors")]
    return "; ".join(kept + [frame_policy()])


def response_headers(upstream_headers) -> dict[str, str]:
    out = {k: v for k, v in upstream_headers.items() if k.lower() not in STRIP_RESP}
    out["Content-Security-Policy"] = rewrite_csp(upstream_headers.get("Content-Security-Policy"))
    out["Cache-Control"] = upstream_headers.get("Cache-Control", "no-store")
    return out


def make_app(target: Target) -> web.Application:
    base = f"http://127.0.0.1:{target.upstream}"
    origin = base

    @web.middleware
    async def loopback_only(request: web.Request, handler):
        if not is_loopback(request.remote):
            return web.Response(status=403, text="loopback only")
        return await handler(request)

    async def start(request: web.Request):
        if target.token_file is None:
            raise web.HTTPFound("/")
        try:
            tok = target.token_file.read_text().strip()
        except OSError:
            return web.Response(status=503, text="engine token not provisioned")
        resp = web.HTTPFound("/#token=" + tok)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        raise resp

    async def health(request: web.Request):
        cors = {}
        if request.headers.get("Origin") in JAEGER_ORIGINS:
            cors = {"Access-Control-Allow-Origin": request.headers["Origin"], "Vary": "Origin"}
        try:
            async with request.app["client"].get(base + "/", timeout=3) as r:
                return web.json_response({"engine": target.name, "upstream": base, "ok": r.status < 500,
                                          "status": r.status}, headers=cors)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"engine": target.name, "upstream": base, "ok": False,
                                      "error": type(exc).__name__}, status=503, headers=cors)

    async def proxy(request: web.Request):
        client: ClientSession = request.app["client"]
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP | {"host", "origin", "referer"}}
        headers["Host"] = f"127.0.0.1:{target.upstream}"
        if "Origin" in request.headers:
            headers["Origin"] = origin
        url = base + request.rel_url.path_qs
        if request.headers.get("Upgrade", "").lower() == "websocket":
            ws_down = web.WebSocketResponse(protocols=request.headers.getall("Sec-WebSocket-Protocol", []))
            await ws_down.prepare(request)
            headers = {k: v for k, v in headers.items() if not k.lower().startswith("sec-websocket")}
            async with client.ws_connect(url, headers=headers, max_msg_size=0) as ws_up:
                async def pump(src, dst):
                    async for msg in src:
                        if msg.type == WSMsgType.TEXT:
                            await dst.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await dst.send_bytes(msg.data)
                        else:
                            break
                    await dst.close()
                await asyncio.gather(pump(ws_down, ws_up), pump(ws_up, ws_down), return_exceptions=True)
            return ws_down
        body = await request.read()
        async with client.request(request.method, url, headers=headers, data=body or None,
                                  allow_redirects=False) as up:
            data = await up.read()
            return web.Response(status=up.status, body=data, headers=response_headers(up.headers))

    async def on_startup(app):
        app["client"] = ClientSession(auto_decompress=True)

    async def on_cleanup(app):
        await app["client"].close()

    app = web.Application(middlewares=[loopback_only], client_max_size=64 * 1024 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/__jaeger/start", start)
    app.router.add_get("/__jaeger/health", health)
    app.router.add_route("*", "/{tail:.*}", proxy)
    return app


async def serve() -> None:
    runners = []
    for t in TARGETS:
        runner = web.AppRunner(make_app(t))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", t.listen).start()
        runners.append(runner)
        print(f"embed proxy {t.name}: http://127.0.0.1:{t.listen} -> 127.0.0.1:{t.upstream}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(serve())
