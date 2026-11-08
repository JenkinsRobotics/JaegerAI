"""Closed Gateway credential consumer; OAuth bearer tokens never reach Gateway."""

from __future__ import annotations

import asyncio
from urllib.parse import urlencode, urlsplit

from jaeger_ai.features.agent_bridge.service import key


class AresGateway:
    def __init__(self, base_url):
        p = urlsplit(base_url)
        if (
            p.scheme != "http"
            or p.hostname != "127.0.0.1"
            or p.username
            or p.password
            or p.path not in ("", "/")
            or p.query
            or p.fragment
        ):
            raise ValueError("Gateway must be an explicit loopback HTTP endpoint")
        self.base_url = base_url.rstrip("/")

    async def _call(self, method, path, body=None):
        # read_token is a consumer, unlike client_token (which can provision).
        from jaeger_ai.core.gateway.caller_auth import read_token
        from jaeger_ai.core.gateway.client import GatewayTurnClient

        def consume():
            token = read_token("ares")
            if not token:
                raise PermissionError("Existing ARES Gateway credential required")
            return GatewayTurnClient(self.base_url, caller="ares", token=token)._call(
                method, path, body
            )

        return await asyncio.to_thread(consume)

    async def list_messages(self, after=0, limit=50):
        return await self._call(
            "GET", "/v1/agent-messages?" + urlencode({"after": after, "limit": limit})
        )

    async def get_thread(self, thread, after=0, limit=50):
        return await self._call(
            "GET",
            f"/v1/agent-threads/{key(thread)}?"
            + urlencode({"after": after, "limit": limit}),
        )

    async def send_message(self, **arguments):
        return await self._call("POST", "/v1/agent-messages", arguments)
