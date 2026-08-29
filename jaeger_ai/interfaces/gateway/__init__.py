"""Messaging Gateway Adapters for JaegerAI.

Adapted from Hermes Agent (`gateway/`).
Provides a gateway interface to bridge multi-channel messaging apps
(Telegram, Discord, Slack, WhatsApp) to JaegerAI's agent protocol.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class BaseMessagingGateway:
    """Base class for multi-channel messaging platform gateways."""

    def __init__(self, platform_name: str, agent_runner: Optional[Callable[[str], Any]] = None):
        self.platform_name = platform_name
        self.agent_runner = agent_runner
        self._running = False

    async def start(self) -> None:
        """Start listening for incoming platform messages."""
        self._running = True
        logger.info(f"Messaging gateway '{self.platform_name}' started.")

    async def stop(self) -> None:
        """Stop gateway listener."""
        self._running = False
        logger.info(f"Messaging gateway '{self.platform_name}' stopped.")

    async def on_message_received(self, user_id: str, message_text: str) -> str:
        """Handle incoming message from platform and dispatch to agent."""
        if not self.agent_runner:
            return "Agent runner not configured."
        try:
            if asyncio.iscoroutinefunction(self.agent_runner):
                reply = await self.agent_runner(message_text)
            else:
                reply = await asyncio.to_thread(self.agent_runner, message_text)
            return str(reply)
        except Exception as e:
            logger.error(f"Gateway turn execution error on {self.platform_name}: {e}")
            return f"Error executing turn: {e}"


from .telegram_adapter import TelegramGateway
from .discord_adapter import DiscordGateway
from .slack_adapter import SlackGateway
from .manager import GatewayManager

__all__ = [
    "BaseMessagingGateway",
    "TelegramGateway",
    "DiscordGateway",
    "SlackGateway",
    "GatewayManager",
]
