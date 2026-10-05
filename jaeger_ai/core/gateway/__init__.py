"""Jaeger Unified Gateway Package.

Decouples the Jaeger Agent Engine from any UI window, enabling persistent,
reconnectable, multi-client sessions across Mac App, Web UI, and CLI.
Modeled after OpenClaw's Gateway architecture.
"""

from .session_store import (
    GatewaySessionStore,
    RequestBusy,
    RequestConflict,
    default_store_path,
)
from .event_bus import GatewayEventBus, GatewayEvent

__all__ = [
    "GatewaySessionStore",
    "RequestBusy",
    "RequestConflict",
    "default_store_path",
    "GatewayEventBus",
    "GatewayEvent",
    "JaegerGatewayApp",
    "DEFAULT_GATEWAY_HOST",
    "DEFAULT_GATEWAY_PORT",
    "create_gateway_server",
    "run_gateway_forever",
]

# The daemon imports aiohttp. PolicyKernel and the agent suite read the stop
# latch without starting a Gateway, so these names load only when asked.
_SERVER_EXPORTS = {
    "JaegerGatewayApp": "JaegerGatewayApp",
    "DEFAULT_GATEWAY_HOST": "DEFAULT_GATEWAY_HOST",
    "DEFAULT_GATEWAY_PORT": "DEFAULT_GATEWAY_PORT",
    "create_gateway_server": "create_gateway_server",
    "run_gateway_forever": "run_gateway_forever",
}


def __getattr__(name: str):
    export = _SERVER_EXPORTS.get(name)
    if export is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import server

    value = getattr(server, export)
    globals()[name] = value
    return value

