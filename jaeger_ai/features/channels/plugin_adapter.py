"""Adapt existing messaging plugin bridges to :class:`ChannelAdapter`.

Discord / Telegram / iMessage keep their own bridge classes. This thin
wrapper registers them on :class:`~jaeger_ai.features.channels.registry.ChannelRegistry`
so outbound sends can go through the channels protocol without rewriting
the plugins.
"""

from __future__ import annotations

from typing import Any

from .adapter import OutboundMessage


class PluginBridgeAdapter:
    """Wrap a plugin bridge that exposes ``start`` / ``stop`` / ``send``."""

    def __init__(self, channel_id: str, bridge: Any) -> None:
        cid = str(channel_id or "").strip().lower()
        if not cid:
            raise ValueError("channel_id is required")
        if bridge is None:
            raise ValueError("bridge is required")
        self.channel_id = cid
        self._bridge = bridge

    def start(self) -> None:
        start = getattr(self._bridge, "start", None)
        if callable(start):
            start()

    def stop(self) -> None:
        stop = getattr(self._bridge, "stop", None)
        if callable(stop):
            stop()

    def send(self, message: OutboundMessage) -> dict[str, Any]:
        send = getattr(self._bridge, "send", None)
        if not callable(send):
            return {"sent": False, "error": f"{self.channel_id} bridge has no send()"}
        result = send(message.recipient_id, message.text)
        if isinstance(result, dict):
            return result
        return {"sent": True, "result": result}


def register_plugin_bridge(channel_id: str, bridge: Any, registry: Any | None = None) -> PluginBridgeAdapter:
    """Register ``bridge`` on the (global) channel registry and return the adapter."""
    from .registry import get_registry

    adapter = PluginBridgeAdapter(channel_id, bridge)
    reg = registry if registry is not None else get_registry()
    reg.register(adapter)
    return adapter
