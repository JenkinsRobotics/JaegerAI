"""Host camera diagnostic and control tools."""

from __future__ import annotations

import os
import urllib.request
from typing import Any

from .grants import _audit, _require


def camera_status() -> dict[str, Any]:
    """Inspect camera device states and availability."""
    capability = "camera.status"
    _require(capability)
    # Probes local camera service if available
    camera_url = os.environ.get("CAMERA_SERVICE_URL", "http://127.0.0.1:8795/status")
    online = False
    try:
        with urllib.request.urlopen(camera_url, timeout=2) as resp:
            online = resp.status == 200
    except Exception:
        online = False
    _audit(capability, outcome="allowed")
    return {"online": online, "configured": False, "devices": []}


def camera_snapshot(device_id: str = "") -> dict[str, Any]:
    """Capture a snapshot frame from an authorized camera."""
    capability = "camera.snapshot"
    _require(capability)
    _audit(capability, outcome="denied", error="No active camera feed")
    return {"captured": False, "error": "Camera service offline"}


def camera_listen(seconds: int = 5) -> dict[str, Any]:
    """Record ambient audio clip from the default input device."""
    capability = "camera.listen"
    _require(capability)
    _audit(capability, outcome="allowed")
    return {"status": "inactive", "duration_seconds": seconds}


def camera_ptz(pan: float = 0.0, tilt: float = 0.0, zoom: float = 1.0) -> dict[str, Any]:
    """Adjust Pan-Tilt-Zoom on a supported camera mount."""
    capability = "camera.ptz"
    _require(capability)
    _audit(capability, outcome="allowed")
    return {"status": "unsupported", "pan": pan, "tilt": tilt, "zoom": zoom}
