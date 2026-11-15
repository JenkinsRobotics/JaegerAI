"""Gateway routes for the phone channels relay (owner/admin only).

GET   /v1/channels/relay        status + sanitized settings (no secrets)
PATCH /v1/channels/relay        delivery toggles / enable flags
POST  /v1/channels/relay/pair   issue a Telegram pairing code (1 h)
POST  /v1/channels/relay/unpair forget the paired Telegram chat
POST  /v1/channels/relay/test   queue a test message to the live channels
"""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web

from .config import load_config, new_pairing_code, read_state, save_config, telegram_token, TELEGRAM_TOKEN_ENV
from .outbox import enqueue


def snapshot() -> dict[str, Any]:
    cfg = load_config()
    status = read_state("status")
    fresh = bool(status) and time.time() - float(status.get("updated_at") or 0) < 30
    tg = cfg.get("telegram") or {}
    im = cfg.get("imessage") or {}
    code = tg.get("pairing_code") if tg.get("allowed_chat_id") is None and float(tg.get("pairing_expires_at") or 0) > time.time() else None
    return {
        "relay_running": fresh,
        "home_session": status.get("home_session"),
        "telegram": {
            "enabled": bool(tg.get("enabled", True)),
            "token_present": bool(telegram_token()),
            "token_env": TELEGRAM_TOKEN_ENV,
            "paired": tg.get("allowed_chat_id") is not None,
            "pairing_code": code,
            "bot_username": (status.get("telegram") or {}).get("bot_username"),
            "live": fresh and bool((status.get("telegram") or {}).get("live")),
            "error": (status.get("telegram") or {}).get("error"),
        },
        "imessage": {
            "enabled": bool(im.get("enabled", True)),
            "send_to": im.get("send_to"),
            "self_handles": im.get("self_handles") or [],
            "live": fresh and bool((status.get("imessage") or {}).get("live")),
            "error": (status.get("imessage") or {}).get("error"),
        },
        "deliver": cfg.get("deliver") or {},
        "counters": status.get("counters") or {},
        "outbox_pending": status.get("outbox_pending"),
    }


def register(gateway: Any) -> None:
    async def get_status(_request: web.Request) -> web.Response:
        return web.json_response(snapshot())

    async def patch(request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else {}
        if not isinstance(body, dict):
            return web.json_response({"error": "Object required"}, status=400)
        cfg = load_config()
        for channel in ("telegram", "imessage"):
            if isinstance(body.get(channel), dict) and "enabled" in body[channel]:
                cfg[channel]["enabled"] = bool(body[channel]["enabled"])
        deliver = body.get("deliver")
        if isinstance(deliver, dict):
            for key in ("schedules", "approvals", "notifications"):
                if key in deliver:
                    cfg["deliver"][key] = bool(deliver[key])
            if deliver.get("fanout") in ("first", "all"):
                cfg["deliver"]["fanout"] = deliver["fanout"]
        save_config(cfg)
        return web.json_response(snapshot())

    async def pair(_request: web.Request) -> web.Response:
        cfg = load_config()
        code = new_pairing_code(cfg)
        return web.json_response({**snapshot(), "pairing_code": code})

    async def unpair(_request: web.Request) -> web.Response:
        cfg = load_config()
        cfg["telegram"]["allowed_chat_id"] = None
        save_config(cfg)
        return web.json_response(snapshot())

    async def test(_request: web.Request) -> web.Response:
        res = enqueue("Test from Jaeger: phone channels are working. Reply here to talk to me.",
                      kind="test", channels=None)
        return web.json_response({"queued": res, **snapshot()})

    router = gateway.app.router
    router.add_get("/v1/channels/relay", get_status)
    router.add_patch("/v1/channels/relay", patch)
    router.add_post("/v1/channels/relay/pair", pair)
    router.add_post("/v1/channels/relay/unpair", unpair)
    router.add_post("/v1/channels/relay/test", test)
