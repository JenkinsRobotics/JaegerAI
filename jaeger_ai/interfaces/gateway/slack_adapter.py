"""Slack gateway adapter for JaegerAI (ported from Hermes Agent)."""

from __future__ import annotations

import asyncio
import logging
import os
import json
from typing import Any, Callable, Optional, List

from jaeger_ai.interfaces.gateway import BaseMessagingGateway

logger = logging.getLogger(__name__)


class SlackGateway(BaseMessagingGateway):
    """Slack Events / Socket Mode gateway messaging adapter."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        app_token: Optional[str] = None,
        allowed_channels: Optional[List[str]] = None,
        agent_runner: Optional[Callable[[str], Any]] = None,
    ):
        super().__init__("slack", agent_runner)
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
        self.app_token = app_token or os.environ.get("SLACK_APP_TOKEN", "")
        env_channels = {
            value.strip() for value in os.environ.get("SLACK_ALLOWED_CHANNEL_IDS", "").split(",")
            if value.strip()
        }
        self.allowed_channels = set(allowed_channels) if allowed_channels is not None else env_channels
        self._task: Optional[asyncio.Task] = None
        self._session: Any = None

    def is_channel_allowed(self, channel_id: str) -> bool:
        return channel_id in self.allowed_channels

    async def handle_slack_event(self, channel_id: str, user_id: str, text: str, thread_ts: Optional[str] = None) -> Optional[dict]:
        """Process incoming Slack message event payload."""
        if not text or not channel_id:
            return None

        if not self.is_channel_allowed(channel_id):
            logger.debug(f"Ignoring Slack message in unmonitored channel {channel_id}")
            return None

        reply_text = await self.on_message_received(user_id, text)
        return {
            "channel": channel_id,
            "text": reply_text,
            "thread_ts": thread_ts,
        }

    async def start(self) -> None:
        if not self.bot_token:
            raise RuntimeError("Slack bot token is required")
        if not self.app_token:
            raise RuntimeError("Slack app token is required for Socket Mode (SLACK_APP_TOKEN)")
        if not self.allowed_channels:
            raise RuntimeError("Slack allowlist is required (SLACK_ALLOWED_CHANNEL_IDS)")
        import aiohttp

        session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {self.app_token}"})
        try:
            async with session.post("https://slack.com/api/apps.connections.open") as response:
                payload = await response.json()
            if not payload.get("ok") or not payload.get("url"):
                raise RuntimeError(f"Slack Socket Mode connection failed: {payload.get('error', 'missing url')}")
        except Exception:
            await session.close()
            raise
        self._session = session
        self._task = asyncio.create_task(self._socket_loop(payload["url"]), name="slack-gateway")
        await super().start()

    async def _socket_loop(self, url: str) -> None:
        import aiohttp

        assert self._session is not None
        async with self._session.ws_connect(url, heartbeat=30) as socket:
            async for message in socket:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                envelope = json.loads(message.data)
                envelope_id = envelope.get("envelope_id")
                if envelope_id:
                    await socket.send_json({"envelope_id": envelope_id})
                event = (envelope.get("payload") or {}).get("event") or {}
                if event.get("type") != "message" or event.get("bot_id") or event.get("subtype"):
                    continue
                response = await self.handle_slack_event(
                    event.get("channel", ""), event.get("user", ""),
                    event.get("text", ""), event.get("thread_ts") or event.get("ts"),
                )
                if response is not None:
                    await self._post_message(response)

    async def _post_message(self, payload: dict) -> None:
        assert self._session is not None
        headers = {"Authorization": f"Bearer {self.bot_token}"}
        async with self._session.post(
            "https://slack.com/api/chat.postMessage", json=payload, headers=headers
        ) as response:
            result = await response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Slack message send failed: {result.get('error', 'unknown error')}")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._session is not None:
            await self._session.close()
            self._session = None
        await super().stop()


__all__ = ["SlackGateway"]
