"""Telegram plugin — bridges the agent to Telegram chats.

Inbound: messages from allowlisted chats (TELEGRAM_ALLOWED_CHAT_IDS) are
forwarded to the agent. Outbound: send_message("telegram", chat_id, text)
pushes proactive messages via the bridge registry.
"""

from __future__ import annotations

from .bridge import TelegramBridge

__all__ = ["TelegramBridge"]
