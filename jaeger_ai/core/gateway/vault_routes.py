"""Credential vault for the owner (parity P24: logins and keys never in chat).

``GET  /v1/vault/secrets``  — names only, never values.
``POST /v1/vault/secrets``  — {"name": "GITHUB_TOKEN", "value": "..."}; written
straight to ``<instance>/credentials/<name>`` (0600) by the vault, never into a
chat transcript, the event log, or a model context. The agent asks with
``request_secret``: the chat shows a masked card that posts here, and the tool
only learns that the name now exists (it reads the value with get_credential
inside a tool call).

Owner-only: unlisted POST routes need the ``admin`` grant; the WebUI proxy
forwards only these paths. Values are never logged.
"""
from __future__ import annotations

import logging
import re

from aiohttp import web

logger = logging.getLogger("jaeger.vault")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _layout():
    from jaeger_agent.core.workspace import _require_layout

    return _require_layout()


def register(gateway) -> None:
    async def names(_request: web.Request) -> web.Response:
        from jaeger_agent.core import credentials as creds

        try:
            return web.json_response({"names": creds.list_credentials(_layout())})
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"names": [], "error": type(exc).__name__}, status=503)

    async def save(request: web.Request) -> web.Response:
        from jaeger_agent.core import credentials as creds

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        name = str(body.get("name") or "").strip()
        value = body.get("value")
        if not _NAME.match(name):
            return web.json_response({"ok": False, "error": "name: letters, digits, _ . - (max 64)"}, status=400)
        if not isinstance(value, str) or not value:
            return web.json_response({"ok": False, "error": "value is required"}, status=400)
        try:
            creds.set_credential(_layout(), name, value)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"ok": False, "error": type(exc).__name__}, status=500)
        logger.info("vault: saved %s (value not logged)", name)
        session_id = str(body.get("session_id") or "")
        if session_id:
            gateway.event_bus.publish(session_id, "secret.resolved", {"name": name, "status": "saved"})
        return web.json_response({"ok": True, "name": name})

    gateway.app.router.add_get("/v1/vault/secrets", names)
    gateway.app.router.add_post("/v1/vault/secrets", save)
