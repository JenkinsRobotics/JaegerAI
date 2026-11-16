"""Mac actions from the phone web app (parity P11).

``GET  /v1/mac/status``  — battery, volume, Wi-Fi, front app (no content).
``POST /v1/mac/action``  — {"action": "lock_screen" | "display_off" | "open_app" | "status", "app": "Safari"}

Owner-only: unlisted POST routes need the ``admin`` grant (caller_auth), and
the WebUI proxy (features/webui/api/jaeger_sessions.py) forwards only these two
paths. The fixed action list is deliberate; anything broader goes through a
chat turn so Autonomy and the approval flow still apply. Every action is
logged on the ``jaeger.mac_actions`` logger.
"""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

logger = logging.getLogger("jaeger.mac_actions")

PHONE_ACTIONS = ("lock_screen", "display_off", "open_app", "status")


def _run(action: str, app: str | None) -> dict:
    from jaeger_agent.tools.system_control import system_control

    return system_control(action, app if action == "open_app" else None)


def register(gateway) -> None:
    async def status(_request: web.Request) -> web.Response:
        result = await asyncio.to_thread(_run, "status", None)
        return web.json_response(result)

    async def action(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        name = str(body.get("action") or "").strip().lower()
        app = str(body.get("app") or "").strip() or None
        if name not in PHONE_ACTIONS:
            return web.json_response({"ok": False, "error": f"action must be one of {PHONE_ACTIONS}"}, status=400)
        if name == "open_app" and not app:
            return web.json_response({"ok": False, "error": "open_app needs an app name"}, status=400)
        result = await asyncio.to_thread(_run, name, app)
        ok = not (isinstance(result, dict) and result.get("error"))
        logger.info("mac action %s%s from %s: %s", name, f" ({app})" if app else "",
                    request.headers.get("X-Jaeger-Caller", "owner"), "ok" if ok else result.get("error"))
        return web.json_response({"ok": ok, "action": name, "result": result}, status=200 if ok else 502)

    gateway.app.router.add_get("/v1/mac/status", status)
    gateway.app.router.add_post("/v1/mac/action", action)
