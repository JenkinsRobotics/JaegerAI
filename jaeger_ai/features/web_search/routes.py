"""Gateway routes POST /v1/search and POST /v1/fetch (scope ``search``, loopback only).

Each call publishes a ``search.query`` / ``search.fetch`` row on the global
activity stream, attributed to the authenticated caller.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging

from aiohttp import web

from . import service

logger = logging.getLogger(__name__)


def register(gateway):
    limiter = service.RateLimiter()
    state: dict = {}

    def cache():
        if "cache" not in state:
            state["cache"] = service.SearchCache()
        return state["cache"]

    def activity(kind, caller, data):
        try:
            gateway.event_bus.publish("*", kind, {"caller": {"caller_id": caller, "caller_kind": "mcp"}, **data})
        except Exception:  # noqa: BLE001 - never fail the call for a feed row
            logger.warning("search activity failed", exc_info=True)

    def guard(request):
        if not request.remote or not ipaddress.ip_address(request.remote).is_loopback:
            raise service.SearchError("Loopback required", 403)
        if request.content_length and request.content_length > 8192:
            raise service.SearchError("Payload too large", 413)

    async def do_search(request):
        caller = request["caller"].name
        try:
            guard(request)
            body = await request.json()
            limiter.check(caller, "search")
            out = await asyncio.to_thread(
                service.search, body.get("query", ""), limit=body.get("limit", 8),
                categories=body.get("categories") or "general", language=body.get("language") or "",
                time_range=body.get("time_range") or "", cache=cache())
        except service.SearchError as exc:
            return web.json_response({"error": str(exc)}, status=exc.status)
        except (ValueError, TypeError, AttributeError):
            return web.json_response({"error": "Invalid search request"}, status=400)
        activity("search.query", caller, {"query": out["query"][:200], "results": len(out["results"]),
                                          "cached": out["cached"], "status": "done"})
        return web.json_response(out)

    async def do_fetch(request):
        caller = request["caller"].name
        try:
            guard(request)
            body = await request.json()
            limiter.check(caller, "fetch")
            out = await asyncio.to_thread(service.fetch, body.get("url", ""),
                                          max_chars=body.get("max_chars", 20_000), cache=cache())
        except service.SearchError as exc:
            return web.json_response({"error": str(exc)}, status=exc.status)
        except (ValueError, TypeError, AttributeError):
            return web.json_response({"error": "Invalid fetch request"}, status=400)
        activity("search.fetch", caller, {"url": out["final_url"][:300], "chars": len(out["text"]),
                                          "cached": out["cached"], "status": "done"})
        return web.json_response(out)

    gateway.app.router.add_post("/v1/search", do_search)
    gateway.app.router.add_post("/v1/fetch", do_fetch)
