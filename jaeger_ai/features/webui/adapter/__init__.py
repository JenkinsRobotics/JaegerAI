"""WebUI HTTP adapter package.

Bridges Hermes WebUI frontend and API calls to Jaeger backend.
"""
from .server import HermesWebUIAdapterServer
from .bridge_client import BridgeClient

__all__ = ["HermesWebUIAdapterServer", "BridgeClient"]
