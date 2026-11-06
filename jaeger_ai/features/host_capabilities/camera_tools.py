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
    # Live probe: enumerate decodable video devices via OpenCV (no frame written).
    devices: list[dict[str, Any]] = []
    try:
        import cv2  # noqa: PLC0415 — optional dep, probed defensively

        for index in range(4):
            cap = cv2.VideoCapture(index)
            opened = cap.isOpened()
            ok, frame = cap.read() if opened else (False, None)
            cap.release()
            if opened and ok and frame is not None:
                devices.append({"index": index, "shape": list(frame.shape)})
    except Exception:
        devices = []
    # Also probe the optional local camera service, if configured.
    camera_url = os.environ.get("CAMERA_SERVICE_URL", "http://127.0.0.1:8795/status")
    online = False
    try:
        with urllib.request.urlopen(camera_url, timeout=2) as resp:
            online = resp.status == 200
    except Exception:
        online = False
    _audit(capability, outcome="allowed")
    return {"online": online, "configured": bool(devices), "devices": devices}


def camera_snapshot(device_id: str = "") -> dict[str, Any]:
    """Capture a snapshot frame from an authorized camera.

    vNext M4: real capture via OpenCV into a loopback file, then (optionally)
    described by the local MLX VLM. Grant-gated and audit-logged like every
    other host capability; capture itself is Tier 1 read-only sensing.
    """
    capability = "camera.snapshot"
    _require(capability)
    try:
        import cv2  # noqa: PLC0415

        index = int(device_id) if str(device_id).isdigit() else 0
        cap = cv2.VideoCapture(index)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        if not ok or frame is None:
            _audit(capability, outcome="denied", error=f"no frame from device {index}")
            return {"captured": False, "error": f"no frame from device {index}"}
        out = os.environ.get("JAEGER_CAMERA_SNAPSHOT", "/tmp/jaeger-camera-snapshot.jpg")
        cv2.imwrite(out, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        result: dict[str, Any] = {"captured": True, "path": out, "device": index, "shape": list(frame.shape)}
        # Best-effort local description with the MLX VLM; never fails the capture.
        try:
            from mlx_vlm import generate, load  # noqa: PLC0415

            model, processor = load("vikhyatk/moondream2")
            desc = generate(model, processor, "Describe what you see in this image in one sentence.", image=out, max_tokens=120, verbose=False)
            result["description"] = desc.text
        except Exception as exc:
            result["description"] = None
            result["description_error"] = str(exc)[:120]
        _audit(capability, outcome="allowed")
        return result
    except ImportError:
        _audit(capability, outcome="denied", error="opencv unavailable")
        return {"captured": False, "error": "opencv unavailable"}


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
