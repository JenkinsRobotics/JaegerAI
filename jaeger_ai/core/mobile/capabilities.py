"""Mobile capabilities — camera, location, notifications.

These classes define the capabilities that mobile nodes can expose
and provide the agent-facing tools to use them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class MobileCapabilities:
    """Capabilities advertised by a mobile node."""
    camera: bool = False
    location: bool = False
    notifications: bool = False
    files: bool = False
    shortcuts: bool = False  # iOS Shortcuts / Android Intents
    
    def to_list(self) -> list[str]:
        """Convert to capability list."""
        caps = []
        if self.camera:
            caps.append("camera")
        if self.location:
            caps.append("location")
        if self.notifications:
            caps.append("notifications")
        if self.files:
            caps.append("files")
        if self.shortcuts:
            caps.append("shortcuts")
        return caps
    
    @classmethod
    def from_list(cls, caps: list[str]) -> "MobileCapabilities":
        """Create from capability list."""
        return cls(
            camera="camera" in caps,
            location="location" in caps,
            notifications="notifications" in caps,
            files="files" in caps,
            shortcuts="shortcuts" in caps,
        )


class CameraCapability:
    """Camera capability — take photos from mobile device."""

    name = "camera"
    commands = ["camera.list", "camera.snap", "camera.clip"]
    
    def __init__(self, node_server):
        self.node_server = node_server
    
    async def list_cameras(self, node_id: str) -> dict[str, Any]:
        """List available cameras on a device."""
        return await self.node_server.invoke(node_id, "camera.list", {})
    
    async def take_photo(
        self,
        node_id: str,
        *,
        quality: str = "high",
        save_to_disk: bool = True,
        output_path: Path | None = None,
    ) -> dict[str, Any]:
        """Take a photo using the device camera.
        
        Args:
            node_id: The mobile node ID
            quality: Photo quality (low, medium, high)
            save_to_disk: Whether to save to local disk
            output_path: Where to save the photo
            
        Returns:
            Photo data including base64 image
        """
        params = {
            "quality": quality,
            "saveToCameraRoll": False,
        }
        
        result = await self.node_server.invoke(node_id, "camera.snap", params, timeout=30.0)
        
        if save_to_disk and result.get("ok") and result.get("dataJSON"):
            import base64
            import json
            
            data = json.loads(result["dataJSON"])
            image_b64 = data.get("imageBase64", "")
            
            if image_b64 and output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(base64.b64decode(image_b64))
                logger.info(f"Photo saved to {output_path}")
                result["saved_to"] = str(output_path)
        
        return result


class LocationCapability:
    """Location capability — get GPS location from mobile device."""

    name = "location"
    commands = ["location.get"]
    
    def __init__(self, node_server):
        self.node_server = node_server
    
    async def get_location(
        self,
        node_id: str,
        *,
        high_accuracy: bool = False,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Get current location from a device.
        
        Args:
            node_id: The mobile node ID
            high_accuracy: Use GPS instead of network location
            timeout: Timeout in seconds
            
        Returns:
            Location data (latitude, longitude, accuracy, timestamp)
        """
        params = {
            "highAccuracy": high_accuracy,
            "timeoutMs": int(timeout * 1000),
        }
        
        result = await self.node_server.invoke(node_id, "location.get", params, timeout=timeout + 5)
        return result


class NotificationCapability:
    """Notification capability — send push notifications to mobile device."""

    name = "notifications"
    commands = ["notify.send"]
    
    def __init__(self, node_server):
        self.node_server = node_server
    
    async def send_notification(
        self,
        node_id: str,
        title: str,
        body: str,
        *,
        priority: str = "default",
        actions: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Send a push notification to a device.
        
        Args:
            node_id: The mobile node ID
            title: Notification title
            body: Notification body
            priority: Priority (low, default, high)
            actions: Optional action buttons
            
        Returns:
            Delivery status
        """
        params = {
            "title": title,
            "body": body,
            "priority": priority,
        }
        if actions:
            params["actions"] = actions
        
        result = await self.node_server.invoke(node_id, "notify.send", params, timeout=10.0)
        return result


def create_mobile_tools(node_server) -> dict[str, Callable]:
    """Create agent-facing tools for mobile capabilities.

    Returns a dict of tool name → callable for registration with the agent.
    """
    camera = CameraCapability(node_server)
    location = LocationCapability(node_server)
    notifications = NotificationCapability(node_server)
    
    async def mobile_camera_snap(node_id: str, quality: str = "high", save_path: str = "") -> dict:
        """Take a photo using a mobile device's camera."""
        output_path = Path(save_path) if save_path else None
        return await camera.take_photo(node_id, quality=quality, output_path=output_path)
    
    async def mobile_location_get(node_id: str, high_accuracy: bool = False) -> dict:
        """Get the current GPS location of a mobile device."""
        return await location.get_location(node_id, high_accuracy=high_accuracy)
    
    async def mobile_notify(node_id: str, title: str, body: str, priority: str = "default") -> dict:
        """Send a push notification to a mobile device."""
        return await notifications.send_notification(node_id, title, body, priority=priority)
    
    async def mobile_devices_list() -> dict:
        """List all connected mobile devices."""
        nodes = node_server.list_nodes()
        return {"devices": [n.to_dict() for n in nodes]}
    
    return {
        "mobile_camera_snap": mobile_camera_snap,
        "mobile_location_get": mobile_location_get,
        "mobile_notify": mobile_notify,
        "mobile_devices_list": mobile_devices_list,
    }


__all__ = [
    "MobileCapabilities",
    "CameraCapability",
    "LocationCapability",
    "NotificationCapability",
    "create_mobile_tools",
]
