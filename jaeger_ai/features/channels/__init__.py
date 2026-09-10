"""Multi-channel ingress feature.

Channels are faces into Jaeger. Jaeger remains the reasoner; adapters here
(and existing ``jaeger_ai/plugins/{discord,telegram,imessage}``) only ferry
messages. Expand via :mod:`jaeger_ai.features.channels.registry`.
"""

from .adapter import ChannelAdapter, InboundMessage, OutboundMessage
from .catalog import ChannelCatalogEntry, bundled_catalog
from .plugin_adapter import PluginBridgeAdapter, register_plugin_bridge
from .registry import ChannelRegistry, get_registry

__all__ = [
    "ChannelAdapter",
    "ChannelCatalogEntry",
    "ChannelRegistry",
    "InboundMessage",
    "OutboundMessage",
    "PluginBridgeAdapter",
    "bundled_catalog",
    "get_registry",
    "register_plugin_bridge",
]
