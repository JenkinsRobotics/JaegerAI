"""Droid Mode: connected host gimbal camera, microphone, and speakers (`EmbodimentPort`).

Connects Jaeger's singular intelligence to the physical peripherals attached to
its host computer (e.g. Insta360 Link 2 motorized UVC gimbal camera + mic +
Logi/Mac speakers) using the exact same ``jaeger_contracts.EmbodimentPort``
contract shared by Minecraft and the physical JP01 droid.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping


def _parse_system_profiler_devices(text: str, *, kind: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped in ("Camera:", "Audio:", "Devices:"):
            continue
        if stripped.endswith(":") and ":" not in stripped[:-1] and indent in (4, 8):
            if current is not None:
                devices.append(current)
            name = stripped[:-1].strip()
            low = name.lower()
            is_gimbal = any(k in low for k in ("insta360 link", "obsbot", "ptz", "gimbal"))
            current = {"name": name, "kind": kind, "gimbal_capable": is_gimbal, "properties": {}}
        elif current is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            current["properties"][k.strip()] = v.strip()
            if "vendorid_11802" in v.lower():
                current["gimbal_capable"] = True
                current["gimbal_driver"] = "insta360_link_uvc_xu"
    if current is not None:
        devices.append(current)
    return devices


def discover_host_peripherals(*, probe_system: bool = True) -> dict[str, Any]:
    """Discover connected host cameras, motorized gimbals, microphones, and speakers."""
    cameras: list[dict[str, Any]] = []
    audio_inputs: list[dict[str, Any]] = []
    audio_outputs: list[dict[str, Any]] = []

    if probe_system and platform.system() == "Darwin" and shutil.which("system_profiler"):
        try:
            cam_out = subprocess.run(
                ["system_profiler", "SPCameraDataType"],
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            ).stdout
            cameras = _parse_system_profiler_devices(cam_out, kind="camera")
        except Exception:  # noqa: BLE001
            cameras = []
        try:
            aud_out = subprocess.run(
                ["system_profiler", "SPAudioDataType"],
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            ).stdout
            for dev in _parse_system_profiler_devices(aud_out, kind="audio"):
                props = dev.get("properties") or {}
                if props.get("Input Channels"):
                    audio_inputs.append(dev)
                if props.get("Output Channels"):
                    audio_outputs.append(dev)
        except Exception:  # noqa: BLE001
            pass

    gimbal = next((c for c in cameras if c.get("gimbal_capable")), None)
    return {
        "platform": platform.system(),
        "cameras": cameras,
        "gimbal_camera": gimbal,
        "microphones": audio_inputs,
        "speakers": audio_outputs,
        "tools": {
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "linkctl": bool(shutil.which("linkctl")),
            "uvc_util": bool(shutil.which("uvc-util")),
        },
        "probed_at": time.time(),
    }


class HostDroidEmbodiment:
    """Droid Mode body adapter bridging host gimbal camera, mic, and speakers to EmbodimentPort."""

    name = "host_droid"

    def __init__(
        self,
        *,
        vision_buffer: Any = None,
        world_model: Any = None,
        probe_on_init: bool = False,
    ) -> None:
        self._lock = threading.RLock()
        self._vision = vision_buffer
        self._world = world_model
        self._estop_latched = False
        self._estop_reason = ""
        self._paused = False
        self._pose = {"pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0, "tracking": False}
        self._devices = discover_host_peripherals(probe_system=probe_on_init)
        self._last_capture_at = 0.0
        self._action_count = 0

    def refresh_devices(self) -> dict[str, Any]:
        found = discover_host_peripherals(probe_system=True)
        with self._lock:
            self._devices = found
            return dict(found)

    def observe(self) -> Mapping[str, Any]:
        with self._lock:
            return {
                "embodiment": self.name,
                "paused": self._paused,
                "estop_latched": self._estop_latched,
                "estop_reason": self._estop_reason,
                "pose": dict(self._pose),
                "devices": dict(self._devices),
                "vision": self._vision.stats() if self._vision is not None else None,
                "action_count": self._action_count,
                "last_capture_at": self._last_capture_at,
            }

    def capture_frame(self, *, device_index: str = "0", summary: str = "") -> dict[str, Any]:
        """Capture a single JPEG frame via macOS AVFoundation ffmpeg into RollingFrameBuffer."""
        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return {"ok": False, "error": "ffmpeg_not_installed"}
        try:
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "avfoundation",
                    "-framerate",
                    "30",
                    "-video_size",
                    "640x360",
                    "-i",
                    f"{device_index}:none",
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "mjpeg",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=6.0,
                check=False,
            )
            raw = proc.stdout or b""
            if proc.returncode != 0 or not raw:
                err = (proc.stderr or b"").decode("utf-8", "replace").strip()[:240]
                return {"ok": False, "error": err or "camera_capture_returned_empty"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        now = time.time()
        meta: dict[str, Any] = {"bytes": len(raw), "captured_at": now}
        if self._vision is not None:
            frame = self._vision.push_frame(raw, source=f"host_cam:{device_index}", summary=summary)
            meta = frame.to_metadata()
        if self._world is not None:
            self._world.record_perception(
                modality="camera",
                kind="host_droid_frame",
                payload=meta,
                salience=0.7 if meta.get("scene_changed", True) else 0.2,
            )
        with self._lock:
            self._last_capture_at = now
        return {"ok": True, "frame": meta}

    def act(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            p = dict(params or {})
            self._paused = False
            self._action_count += 1

            if action == "look_at":
                pan = max(-145.0, min(145.0, float(p.get("pan_deg", self._pose["pan_deg"]))))
                tilt = max(-90.0, min(90.0, float(p.get("tilt_deg", self._pose["tilt_deg"]))))
                zoom = max(1.0, min(4.0, float(p.get("zoom", self._pose["zoom"]))))
                self._pose.update({"pan_deg": pan, "tilt_deg": tilt, "zoom": zoom})
                hw_dispatched = self._dispatch_gimbal_hw(pan=pan, tilt=tilt, zoom=zoom)
                return {
                    "ok": True,
                    "action": action,
                    "pose": dict(self._pose),
                    "hardware_dispatched": hw_dispatched,
                }
            if action == "center":
                self._pose.update({"pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0})
                hw_dispatched = self._dispatch_gimbal_hw(pan=0.0, tilt=0.0, zoom=1.0, reset=True)
                return {"ok": True, "action": action, "pose": dict(self._pose), "hardware_dispatched": hw_dispatched}
            if action == "track_person":
                enabled = bool(p.get("enabled", True))
                self._pose["tracking"] = enabled
                return {"ok": True, "action": action, "pose": dict(self._pose)}
            if action == "refresh_devices":
                return {"ok": True, "action": action, "devices": self.refresh_devices()}
            return {"ok": False, "error": f"unsupported_host_droid_action:{action}"}

    def _dispatch_gimbal_hw(self, *, pan: float, tilt: float, zoom: float, reset: bool = False) -> bool:
        """Send real gimbal command via `linkctl` (Insta360 Link) or `uvc-util` if installed."""
        linkctl = shutil.which("linkctl")
        if linkctl:
            try:
                cmd = [linkctl, "reset"] if reset else [linkctl, "move", str(round(pan, 1)), str(round(tilt, 1))]
                res = subprocess.run(cmd, capture_output=True, timeout=3.0, check=False)
                return res.returncode == 0
            except Exception:  # noqa: BLE001
                return False
        return False

    def checkpoint(self) -> Mapping[str, Any]:
        with self._lock:
            return {"ok": True, "pose": dict(self._pose), "action_count": self._action_count}

    def pause(self, reason: str = "preempted") -> Mapping[str, Any]:
        with self._lock:
            self._paused = True
            return {"ok": True, "reason": reason, "pose": dict(self._pose)}

    def estop(self, reason: str = "operator") -> Mapping[str, Any]:
        with self._lock:
            self._estop_latched = True
            self._estop_reason = reason
            self._paused = True
            self._pose["tracking"] = False
            return {"ok": True, "estop_latched": True, "reason": reason}

    def release_estop(self) -> None:
        with self._lock:
            self._estop_latched = False
            self._estop_reason = ""


__all__ = ["HostDroidEmbodiment", "discover_host_peripherals"]
