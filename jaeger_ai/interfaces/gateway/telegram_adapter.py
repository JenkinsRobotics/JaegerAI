"""Telegram messaging gateway adapter for JaegerAI (ported from Hermes Agent)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional, List

from jaeger_ai.interfaces.gateway import BaseMessagingGateway

logger = logging.getLogger(__name__)


class TelegramGateway(BaseMessagingGateway):
    """Telegram Bot API messaging adapter."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        allowed_users: Optional[List[int]] = None,
        agent_runner: Optional[Callable[[str], Any]] = None,
    ):
        super().__init__("telegram", agent_runner)
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        env_users = {
            int(value.strip()) for value in os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
            if value.strip().lstrip("-").isdigit()
        }
        self.allowed_users = set(allowed_users) if allowed_users is not None else env_users
        self._task: Optional[asyncio.Task] = None
        self._application: Any = None

    def is_user_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_users

    async def handle_update(self, update: dict) -> Optional[dict]:
        """Process incoming Telegram Bot API update."""
        message = update.get("message", {})
        text = message.get("text", "")
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        user = message.get("from", {})
        user_id = user.get("id")

        if not text or not chat_id:
            return None

        if user_id is None or not self.is_user_allowed(user_id):
            logger.warning(f"Unauthorized Telegram access attempt by user_id {user_id}")
            return {
                "chat_id": chat_id,
                "text": "Access denied: Unauthorized Telegram user ID.",
            }

        reply_text = await self.on_message_received(str(user_id or chat_id), text)
        return {
            "chat_id": chat_id,
            "text": reply_text,
        }

    async def start(self) -> None:
        if not self.bot_token:
            raise RuntimeError("Telegram bot token is required")
        if not self.allowed_users:
            raise RuntimeError("Telegram allowlist is required (TELEGRAM_ALLOWED_USER_IDS)")
        from telegram.ext import Application, MessageHandler, filters

        app = Application.builder().token(self.bot_token).build()

        async def receive(update: Any, _context: Any) -> None:
            response = await self.handle_update(update.to_dict())
            if response is not None:
                await app.bot.send_message(**response)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive))
        await app.initialize()
        await app.start()
        if app.updater is None:
            await app.stop()
            await app.shutdown()
            raise RuntimeError("Telegram polling updater is unavailable")
        await app.updater.start_polling()
        self._application = app
        await super().start()

    async def stop(self) -> None:
        app, self._application = self._application, None
        if app is not None:
            if app.updater is not None and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
        await super().stop()


__all__ = ["TelegramGateway"]
