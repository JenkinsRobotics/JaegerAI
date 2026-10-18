"""Jaeger WebUI feature package.

Unified home for Web UI services, adapters, branding assets, and runners.
"""
from .service.service import WebUIService, webui_urls
from .service.profile_layout import profile_display_name
from .adapter.server import HermesWebUIAdapterServer
from .adapter.bridge_client import BridgeClient

__all__ = [
    "WebUIService",
    "webui_urls",
    "profile_display_name",
    "HermesWebUIAdapterServer",
    "BridgeClient",
]
