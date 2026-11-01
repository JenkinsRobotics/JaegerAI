"""Gateway routes for AppControl (loopback only).

GET  /v1/apps                              -> list (read)
GET  /v1/apps/proposals                    -> proposals (read)
GET  /v1/apps/proposals/{pid}              -> one proposal (read)
GET  /v1/apps/{app}                        -> status (read)
GET  /v1/apps/{app}/config?index=0         -> redacted config (read)
POST /v1/apps/{app}/proposals              -> {action, prompt?} or {ops, index?, reason?} (turn) - never applies
POST /v1/apps/proposals/{pid}/decision     -> {approve: bool} (approve scope AND webui/menubar caller only)
POST /v1/apps/proposals/{pid}/rollback     -> (approve scope AND webui/menubar caller only)
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging

from aiohttp import web

from .service import AppControl, AppControlError

logger = logging.getLogger(__name__)


def register(gateway, control: AppControl | None = None):
    def publish(kind, data):
        try:
            gateway.event_bus.publish("*", kind, data)
        except Exception:  # noqa: BLE001
            logger.warning("appcontrol activity failed", exc_info=True)

    state = {"control": control}

    def ctl() -> AppControl:
        if state["control"] is None:
            state["control"] = AppControl(publish=publish)
        return state["control"]

    def guard(request):
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise web.HTTPForbidden(text="Loopback required")
        caller = request.get("caller")
        return getattr(caller, "name", None), getattr(caller, "session_prefix", None)

    async def body_of(request):
        if request.content_length and request.content_length > 65536:
            raise web.HTTPRequestEntityTooLarge(max_size=65536, actual_size=request.content_length)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="JSON object required")
        return body

    def wrap(fn):
        async def handler(request):
            try:
                return web.json_response(await fn(request))
            except AppControlError as exc:
                return web.json_response({"error": str(exc)}, status=exc.status)
        return handler

    async def apps(request):
        guard(request)
        return {"apps": await asyncio.to_thread(ctl().apps_list)}

    async def proposals(request):
        guard(request)
        return {"proposals": ctl().proposals(request.query.get("status") or None)}

    async def proposal(request):
        guard(request)
        return ctl().proposal(request.match_info["pid"])

    async def status(request):
        guard(request)
        return await asyncio.to_thread(ctl().app_status, request.match_info["app"])

    async def config(request):
        guard(request)
        try:
            index = int(request.query.get("index", "0"))
        except ValueError:
            raise AppControlError("index must be an integer") from None
        return await asyncio.to_thread(ctl().config_get, request.match_info["app"], index)

    async def propose(request):
        name, _ = guard(request)
        body = await body_of(request)
        app = request.match_info["app"]
        actor = name or "unknown"
        if "ops" in body:
            out = await asyncio.to_thread(ctl().propose_config, app, body.get("ops"), actor,
                                          int(body.get("index") or 0), str(body.get("reason") or ""))
        else:
            out = await asyncio.to_thread(ctl().propose_action, app, str(body.get("action") or ""), actor,
                                          str(body.get("prompt") or ""))
        return out

    async def decision(request):
        name, prefix = guard(request)
        body = await body_of(request)
        if not isinstance(body.get("approve"), bool):
            raise AppControlError("approve must be true or false")
        return await asyncio.to_thread(ctl().decide, request.match_info["pid"], body["approve"], name, prefix)

    async def rollback(request):
        name, prefix = guard(request)
        return await asyncio.to_thread(ctl().rollback, request.match_info["pid"], name, prefix)

    r = gateway.app.router
    r.add_get("/v1/apps", wrap(apps))
    r.add_get("/v1/apps/proposals", wrap(proposals))
    r.add_get("/v1/apps/proposals/{pid}", wrap(proposal))
    r.add_post("/v1/apps/proposals/{pid}/decision", wrap(decision))
    r.add_post("/v1/apps/proposals/{pid}/rollback", wrap(rollback))
    r.add_get("/v1/apps/{app}", wrap(status))
    r.add_get("/v1/apps/{app}/config", wrap(config))
    r.add_post("/v1/apps/{app}/proposals", wrap(propose))
    return state
