"""Multi-channel ingress feature.

Channels are faces into Jaeger. Jaeger remains the reasoner; adapters here
(and existing ``jaeger_ai/plugins/{discord,telegram,imessage}``) only ferry
messages. Expand via :mod:`jaeger_ai.features.channels.registry`.
"""

from .adapter import ChannelAdapter, InboundMessage, OutboundMessage
from .catalog import ChannelCatalogEntry, bundled_catalog
from .registry import ChannelRegistry, get_registry

__all__ = [
    "ChannelAdapter",
    "ChannelCatalogEntry",
    "ChannelRegistry",
    "InboundMessage",
    "OutboundMessage",
    "bundled_catalog",
    "get_registry",
]
