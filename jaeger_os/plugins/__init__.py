"""Plugins — drop-in modules adding external integrations.

A plugin bridges the agent to a specific external service or capability:
Discord, Telegram, iMessage, MCP servers, future Kokoro TTS, Whisper STT,
RealSense perception, YOLO classification, etc.

Each plugin lives in its own subdirectory with:
  • plugin.yaml      — manifest (deps, env vars, registered bridges, tools)
  • <module>.py      — the implementation
  • tests/smoke_test.py — importability check the loader runs before activation

This file holds the **shared bridge registry**. Bridges that successfully
start (i.e. opened a connection with valid credentials) call
`register_bridge("<channel>", self)`. The agent's `send_message(channel,
recipient, text)` tool reads the registry to route outbound messages.

See docs/VOCABULARY.md for the full contract on what is and isn't a plugin.
"""

from __future__ import annotations

import threading
from typing import Any


# {channel_name → bridge_instance}. Populated by each bridge when it
# successfully starts; read by core's send_message tool. A lock guards
# the dict so the gateway can register/deregister without races against
# concurrent tool calls.
_BRIDGES: dict[str, Any] = {}
_BRIDGES_LOCK = threading.Lock()


def register_bridge(name: str, bridge: Any) -> None:
    """Bridges call this from their `start()` once they're connected."""
    with _BRIDGES_LOCK:
        _BRIDGES[name] = bridge


def deregister_bridge(name: str) -> None:
    with _BRIDGES_LOCK:
        _BRIDGES.pop(name, None)


def get_bridge(name: str) -> Any:
    with _BRIDGES_LOCK:
        return _BRIDGES.get(name)


def list_bridges() -> list[str]:
    with _BRIDGES_LOCK:
        return sorted(_BRIDGES.keys())


__all__ = ["register_bridge", "deregister_bridge", "get_bridge", "list_bridges"]
