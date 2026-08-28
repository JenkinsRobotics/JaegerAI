"""Discord gateway adapter for JaegerAI (ported from Hermes Agent)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional, List

from jaeger_ai.interfaces.gateway import BaseMessagingGateway

logger = logging.getLogger(__name__)


class DiscordGateway(BaseMessagingGateway):
    """Discord Bot gateway messaging adapter."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        allowed_channels: Optional[List[int]] = None,
        agent_runner: Optional[Callable[[str], Any]] = None,
    ):
        super().__init__("discord", agent_runner)
        self.bot_token = bot_token or os.environ.get("DISCORD_BOT_TOKEN", "")
        env_channels = {
            int(value.strip()) for value in os.environ.get("DISCORD_ALLOWED_CHANNEL_IDS", "").split(",")
            if value.strip().isdigit()
        }
        self.allowed_channels = set(allowed_channels) if allowed_channels is not None else env_channels
        self._task: Optional[asyncio.Task] = None
        self._client: Any = None

    def is_channel_allowed(self, channel_id: int) -> bool:
        return channel_id in self.allowed_channels

    async def handle_discord_message(self, channel_id: int, user_id: str, content: str) -> Optional[dict]:
        """Process incoming Discord message event payload."""
        if not content:
            return None

        if not self.is_channel_allowed(channel_id):
            logger.debug(f"Ignoring Discord message in unmonitored channel {channel_id}")
            return None

        reply_text = await self.on_message_received(user_id, content)
        return {
            "channel_id": channel_id,
            "content": reply_text,
        }

    async def start(self) -> None:
        if not self.bot_token:
            raise RuntimeError("Discord bot token is required")
        if not self.allowed_channels:
            raise RuntimeError("Discord allowlist is required (DISCORD_ALLOWED_CHANNEL_IDS)")
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_message(message: Any) -> None:
            if message.author == client.user:
                return
            response = await self.handle_discord_message(
                int(message.channel.id), str(message.author.id), message.content or ""
            )
            if response is not None:
                await message.channel.send(response["content"])

        self._client = client
        self._task = asyncio.create_task(client.start(self.bot_token), name="discord-gateway")
        await asyncio.sleep(0)
        await super().start()

    async def stop(self) -> None:
        if self._client is not None and not self._client.is_closed():
            await self._client.close()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._client = None
        await super().stop()


__all__ = ["DiscordGateway"]
