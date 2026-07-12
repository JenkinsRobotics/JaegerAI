"""Discord plugin — bridges the agent to Discord DMs and @mentions.

Inbound: messages from allowlisted users (DISCORD_ALLOWED_USER_IDS) are
forwarded to the agent. Outbound: send_message("discord", user_id, text)
pushes proactive messages via the bridge registry.
"""

from __future__ import annotations

from .bridge import DiscordBridge

__all__ = ["DiscordBridge"]
