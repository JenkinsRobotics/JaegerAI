"""Messaging gateway manager for JaegerAI."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from .telegram_adapter import TelegramGateway
from .discord_adapter import DiscordGateway
from .slack_adapter import SlackGateway

logger = logging.getLogger(__name__)


class GatewayManager:
    """Discovers and manages active messaging gateways."""

    def __init__(self, agent_runner: Optional[Callable[[str], Any]] = None):
        self.agent_runner = agent_runner
        self.gateways: Dict[str, Any] = {}

    def setup_gateways(self) -> Dict[str, Any]:
        """Discover available credentials and instantiate configured gateways."""
        telegram = TelegramGateway(agent_runner=self.agent_runner)
        if telegram.bot_token:
            self.gateways["telegram"] = telegram

        discord = DiscordGateway(agent_runner=self.agent_runner)
        if discord.bot_token:
            self.gateways["discord"] = discord

        slack = SlackGateway(agent_runner=self.agent_runner)
        if slack.bot_token and slack.app_token:
            self.gateways["slack"] = slack

        logger.info(f"Initialized {len(self.gateways)} active messaging gateways.")
        return self.gateways

    async def start_all(self) -> None:
        """Start all configured gateways."""
        for name, gateway in self.gateways.items():
            try:
                await gateway.start()
            except Exception as e:
                logger.error(f"Failed to start gateway '{name}': {e}")

    async def stop_all(self) -> None:
        """Stop all configured gateways."""
        for name, gateway in self.gateways.items():
            try:
                await gateway.stop()
            except Exception as e:
                logger.error(f"Error stopping gateway '{name}': {e}")


__all__ = ["GatewayManager"]
