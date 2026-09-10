"""Bundled channel catalog.

Inspired by OpenClaw ``src/channels/bundled-channel-catalog*.ts`` — a
declarative list of channel ids, aliases, and maturity — without pulling
the TypeScript gateway.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChannelStatus = Literal["live", "thin", "planned"]


@dataclass(frozen=True)
class ChannelCatalogEntry:
    id: str
    label: str
    aliases: tuple[str, ...]
    status: ChannelStatus
    source: str
    order: int = 100


_BUNDLED: tuple[ChannelCatalogEntry, ...] = (
    ChannelCatalogEntry(
        id="discord",
        label="Discord",
        aliases=("discord",),
        status="live",
        source="jaeger_ai/plugins/discord",
        order=10,
    ),
    ChannelCatalogEntry(
        id="telegram",
        label="Telegram",
        aliases=("telegram", "tg"),
        status="live",
        source="jaeger_ai/plugins/telegram",
        order=20,
    ),
    ChannelCatalogEntry(
        id="imessage",
        label="iMessage",
        aliases=("imessage", "imsg", "messages"),
        status="live",
        source="jaeger_ai/plugins/imessage",
        order=30,
    ),
    ChannelCatalogEntry(
        id="slack",
        label="Slack",
        aliases=("slack",),
        status="thin",
        source="jaeger_ai/features/gateway + messaging stubs",
        order=40,
    ),
    ChannelCatalogEntry(
        id="whatsapp",
        label="WhatsApp",
        aliases=("whatsapp", "wa"),
        status="planned",
        source="openclaw/extensions/whatsapp (donor)",
        order=50,
    ),
    ChannelCatalogEntry(
        id="signal",
        label="Signal",
        aliases=("signal",),
        status="planned",
        source="openclaw/extensions/signal (donor)",
        order=60,
    ),
    ChannelCatalogEntry(
        id="matrix",
        label="Matrix",
        aliases=("matrix",),
        status="planned",
        source="openclaw/extensions/matrix (donor)",
        order=70,
    ),
)


def bundled_catalog(*, include_planned: bool = True) -> list[ChannelCatalogEntry]:
    """Return catalog entries sorted by ``order``."""
    rows = list(_BUNDLED)
    if not include_planned:
        rows = [r for r in rows if r.status != "planned"]
    return sorted(rows, key=lambda r: (r.order, r.id))


def lookup_channel(channel_id: str) -> ChannelCatalogEntry | None:
    needle = (channel_id or "").strip().lower()
    if not needle:
        return None
    for entry in _BUNDLED:
        if entry.id == needle or needle in entry.aliases:
            return entry
    return None
