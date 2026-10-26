"""Mobile integration for JaegerAI — no native app required.

Provides:
- Mobile node server (WebSocket endpoint for mobile devices)
- Device pairing (QR code + Ed25519 challenge-response)
- Mobile capabilities (camera, location, notifications)
- PWA enhancement APIs
"""

from .node_server import MobileNodeServer, MobileNode
from .pairing import DevicePairing, PairingManager
from .capabilities import MobileCapabilities, CameraCapability, LocationCapability, NotificationCapability

__all__ = [
    "MobileNodeServer",
    "MobileNode",
    "DevicePairing",
    "PairingManager",
    "MobileCapabilities",
    "CameraCapability",
    "LocationCapability",
    "NotificationCapability",
]
