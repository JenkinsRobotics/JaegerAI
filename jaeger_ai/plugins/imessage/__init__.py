"""iMessage plugin — bridges the agent to macOS Messages.

Inbound: polls ~/Library/Messages/chat.db for new messages from
allowlisted handles. Outbound: AppleScript via the bridge registry.
Requires Full Disk Access for the running Python process.
"""

from __future__ import annotations

from .bridge import IMessageBridge

__all__ = ["IMessageBridge"]
