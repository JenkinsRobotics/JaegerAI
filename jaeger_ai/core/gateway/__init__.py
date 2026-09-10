"""Jaeger Unified Gateway Package.

Decouples the Jaeger Agent Engine from any UI window, enabling persistent,
reconnectable, multi-client sessions across Mac App, Web UI, and CLI.
Modeled after OpenClaw's Gateway architecture.
"""

from .session_store import GatewaySessionStore, default_store_path
from .event_bus import GatewayEventBus, GatewayEvent
from .server import (
    JaegerGatewayApp,
    DEFAULT_GATEWAY_HOST,
    DEFAULT_GATEWAY_PORT,
    create_gateway_server,
    run_gateway_forever,
)

__all__ = [
    "GatewaySessionStore",
    "default_store_path",
    "GatewayEventBus",
    "GatewayEvent",
    "JaegerGatewayApp",
    "DEFAULT_GATEWAY_HOST",
    "DEFAULT_GATEWAY_PORT",
    "create_gateway_server",
    "run_gateway_forever",
]
