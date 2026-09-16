"""Jaeger WebUI feature package.

Unified home for Web UI services, adapters, branding assets, and runners.
"""
from .service.service import WebUIService, webui_urls
from .service.profile_layout import ensure_webui_profile_layout, profile_display_name
from .adapter.server import HermesWebUIAdapterServer
from .adapter.bridge_client import BridgeClient

__all__ = [
    "WebUIService",
    "webui_urls",
    "ensure_webui_profile_layout",
    "profile_display_name",
    "HermesWebUIAdapterServer",
    "BridgeClient",
]
