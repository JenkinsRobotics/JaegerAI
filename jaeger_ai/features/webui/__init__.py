"""Jaeger WebUI feature package.

Backend for the first-party React UI (jaeger_ai/interfaces/ui): HTTP server,
service management and branding assets. Turns execute on the Gateway.
"""
from .service.service import WebUIService, webui_urls
from .service.profile_layout import profile_display_name
from jaeger_ai.interfaces.bridge_client import BridgeClient

__all__ = [
    "WebUIService",
    "webui_urls",
    "profile_display_name",
    "BridgeClient",
]
