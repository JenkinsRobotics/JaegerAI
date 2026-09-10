"""Thin channel adapter contract.

Existing Discord/Telegram/iMessage plugins keep their own bridge classes.
New platforms should implement :class:`ChannelAdapter` and register with
:class:`~jaeger_ai.features.channels.registry.ChannelRegistry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class InboundMessage:
    """One user-facing inbound message normalized for Jaeger."""

    channel_id: str
    sender_id: str
    text: str
    thread_id: str | None = None
    session_hint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundMessage:
    """One outbound reply or proactive send."""

    channel_id: str
    recipient_id: str
    text: str
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChannelAdapter(Protocol):
    """Minimal face contract — start/stop + send. Inbound uses a handler."""

    channel_id: str

    def start(self) -> None:
        """Begin listening (may spawn a background thread/loop)."""

    def stop(self) -> None:
        """Stop listening and release resources."""

    def send(self, message: OutboundMessage) -> dict[str, Any]:
        """Deliver one outbound message. Return a small result dict."""
