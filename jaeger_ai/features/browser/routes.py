"""Authenticated conversation browser; no raw CDP or worker ports reach clients."""
import asyncio
import json
import re
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from .runtime import BrowserRuntime, BrowserUnavailable

PREFIX = "/v1/sessions/{id}/browser"
ACTIONS = frozenset({"viewport", "status", "select", "navigate", "new-tab", "close", "back", "forward", "reload", "click", "type", "press", "snapshot", "scroll", "content", "errors", "screenshot"})


def register(gateway, runtime=None):
    runtime = runtime or BrowserRuntime()

    def session(request):
        sid = request.match_info["id"]
        if not gateway.store.get_session(sid):
            raise web.HTTPNotFound(text="Conversation not found")
        return sid

    async def action(request):
        sid = session(request)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            name = body.get("action", "status")
            if name == "stop":
                await runtime.close_session(sid)
                return web.json_response({"stopped": True})
            if name not in ACTIONS:
                raise ValueError("Unknown browser action")
            worker = await runtime.worker(sid)
            async with ClientSession(timeout=ClientTimeout(total=40)) as client:
                async with client.post(worker.base + "/jaeger/action", json=body, headers=worker.headers) as response:
                    payload = await response.json()
                    if name not in {"status", "viewport"}:
                        gateway.event_bus.publish(sid, "browser.action", {"action": name, "status": "done" if response.status == 200 else "failed", "page_id": payload.get("active")})
                    return web.json_response(payload, status=response.status)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except (BrowserUnavailable, OSError, asyncio.TimeoutError) as exc:
            return web.json_response({"error": str(exc) or "Browser startup timed out"}, status=503)

    def existing(request):
        worker = runtime.workers.get(session(request))
        if not worker or worker.process.returncode is not None:
            raise web.HTTPConflict(text="Open the browser workspace first")
        return worker

    async def viewer(request):
        worker = existing(request)
        page = request.query.get("pageId", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", page):
            raise web.HTTPBadRequest(text="Browser tab required")
        async with ClientSession() as client:
            async with client.get(worker.base + "/v1/sessions/debug", params={"interactive": "true", "showControls": "false", "pageId": page}, headers=worker.headers) as response:
                if response.status != 200:
                    raise web.HTTPBadGateway(text="Browser viewer unavailable")
                html = await response.text()
        cast = f"/v1/sessions/{quote(request.match_info['id'], safe='')}/browser/cast?pageId={quote(page)}"
        replacement = "const baseWsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + " + json.dumps(cast) + ";"
        html, count = re.subn(r"const baseWsUrl = '[^']*';", lambda _: replacement, html)
        if count != 1:
            raise web.HTTPBadGateway(text="Browser viewer contract changed")
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store", "X-Frame-Options": "SAMEORIGIN"})

    async def cast(request):
        worker = existing(request)
        params = {k: v for k, v in request.query.items() if k in {"pageId", "format"}}
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", params.get("pageId", "")):
            raise web.HTTPBadRequest(text="Browser tab required")
        async with ClientSession() as client:
            async with client.ws_connect(worker.base + "/v1/sessions/cast", params=params, headers=worker.headers, max_msg_size=16 * 1024 * 1024) as upstream:
                downstream = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=20)
                await downstream.prepare(request)

                async def forward(source, target):
                    async for message in source:
                        if message.type == WSMsgType.TEXT:
                            await target.send_str(message.data)
                        elif message.type == WSMsgType.BINARY:
                            await target.send_bytes(message.data)
                        else:
                            break

                async def stopped():
                    from jaeger_ai.core.gateway.server import _control_plane_block
                    while not _control_plane_block():
                        await asyncio.sleep(.5)
                    await downstream.close(code=1008, message=b"Jaeger is stopped")

                tasks = [asyncio.create_task(forward(downstream, upstream)), asyncio.create_task(forward(upstream, downstream)), asyncio.create_task(stopped())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    await downstream.close()
                return downstream

    gateway.app.router.add_post(PREFIX + "/action", action)
    gateway.app.router.add_get(PREFIX + "/viewer", viewer)
    gateway.app.router.add_get(PREFIX + "/cast", cast)

    async def cleanup(_):
        await runtime.close()
    gateway.app.on_cleanup.append(cleanup)
    return runtime
