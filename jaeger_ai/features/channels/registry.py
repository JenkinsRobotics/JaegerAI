"""Runtime registry for :class:`ChannelAdapter` implementations."""

from __future__ import annotations

from typing import Any

from .adapter import ChannelAdapter


class ChannelRegistry:
    """Map channel id → adapter. Does not auto-start plugins."""

    def __init__(self) -> None:
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        channel_id = str(getattr(adapter, "channel_id", "") or "").strip().lower()
        if not channel_id:
            raise ValueError("adapter.channel_id is required")
        self._adapters[channel_id] = adapter

    def get(self, channel_id: str) -> ChannelAdapter | None:
        return self._adapters.get((channel_id or "").strip().lower())

    def list_ids(self) -> list[str]:
        return sorted(self._adapters)

    def send(self, channel_id: str, recipient_id: str, text: str, **meta: Any) -> dict[str, Any]:
        from .adapter import OutboundMessage

        adapter = self.get(channel_id)
        if adapter is None:
            return {"sent": False, "error": f"no adapter registered for {channel_id!r}"}
        return adapter.send(
            OutboundMessage(
                channel_id=(channel_id or "").strip().lower(),
                recipient_id=recipient_id,
                text=text,
                thread_id=meta.get("thread_id"),
                metadata={k: v for k, v in meta.items() if k != "thread_id"},
            )
        )


_REGISTRY = ChannelRegistry()


def get_registry() -> ChannelRegistry:
    return _REGISTRY
