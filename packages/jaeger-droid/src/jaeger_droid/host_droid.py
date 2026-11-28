"""Droid Mode: connected host gimbal camera, microphone, and speakers (`EmbodimentPort`).

Connects Jaeger's singular intelligence to the physical peripherals attached to
its host computer (e.g. Insta360 Link 2 motorized UVC gimbal camera + mic +
Logi/Mac speakers) using the exact same ``jaeger_contracts.EmbodimentPort``
contract shared by Minecraft and the physical JP01 droid.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Mapping

from .reflex import DroidReflexController

PARK_PAN_DEG: float = 0.0
PARK_TILT_DEG: float = -85.0
UVC_ARCSEC_PER_DEG: int = 3600


def _resolve_droid_ptz() -> str | None:
    """Resolve the local `droid-ptz` UVC gimbal CLI if installed and executable."""
    env_state = (os.environ.get("JAEGER_STATE_DIR") or "").strip()
    state_dir = Path(env_state).expanduser() if env_state else (Path.home() / ".jaeger")
    candidate = state_dir / "droid" / "bin" / "droid-ptz"
    try:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    except OSError:
        pass
    return shutil.which("droid-ptz")


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
            "droid_ptz": bool(_resolve_droid_ptz()),
            "ffmpeg": bool(shutil.which("ffmpeg")),
            "linkctl": bool(shutil.which("linkctl")),
            "uvc_util": bool(shutil.which("uvc-util")),
        },
        "probed_at": time.time(),
    }


class HostDroidEmbodiment:
    """Droid Mode body adapter bridging host gimbal camera, mic, and speakers to EmbodimentPort."""

    name = "host_droid"
    PARK_PAN_DEG: float = PARK_PAN_DEG
    PARK_TILT_DEG: float = PARK_TILT_DEG

    def __init__(
        self,
        *,
        vision_buffer: Any = None,
        world_model: Any = None,
        probe_on_init: bool = False,
        on_reflex_event: Callable[[str, Mapping[str, Any]], None] | None = None,
        auto_park_enabled: bool = True,
        idle_park_s: float = 600.0,
    ) -> None:
        self._lock = threading.RLock()
        self._vision = vision_buffer
        self._world = world_model
        self._estop_latched = False
        self._estop_reason = ""
        self._paused = False
        self._sleeping = False
        self._active_stream_proc: asyncio.subprocess.Process | None = None
        self._pose = {"pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0, "tracking": False}
        self._last_dispatched_zoom = 1.0
        self._devices = discover_host_peripherals(probe_system=probe_on_init)
        self._last_capture_at = 0.0
        self._action_count = 0
        self._last_track_move_at = 0.0
        self.reflex = DroidReflexController(
            is_awake=lambda: not self._sleeping,
            is_estop=lambda: self._estop_latched,
            sleep_fn=lambda: self.sleep(reason="idle_auto_park"),
            on_event=on_reflex_event,
            auto_park_enabled=auto_park_enabled,
            idle_park_s=idle_park_s,
        )
        if probe_on_init:
            self.sync_hardware_state()

    def sync_hardware_state(self) -> dict[str, Any] | None:
        """Read actual gimbal hardware pose and reconcile sleeping/parked state truthfully."""
        pose = self.read_gimbal_pose()
        if pose is None:
            return None
        with self._lock:
            self._pose["pan_deg"] = float(pose["pan_deg"])
            self._pose["tilt_deg"] = float(pose["tilt_deg"])
            self._pose["zoom"] = float(pose["zoom"])
            self._last_dispatched_zoom = float(pose["zoom"])
            # Physical Insta360 privacy park tilts lens downward (~ -85°).
            if float(pose["tilt_deg"]) <= -75.0:
                self._sleeping = True
                self._paused = True
                self._pose["tracking"] = False
            else:
                self._sleeping = False
        return pose

    def _voice_enrolled(self) -> bool:
        env_state = (os.environ.get("JAEGER_STATE_DIR") or "").strip()
        state_dir = Path(env_state).expanduser() if env_state else (Path.home() / ".jaeger")
        return (state_dir / "droid-speaker.npy").is_file()

    def _step_face_tracking(self, offset: tuple[float, float] | None) -> None:
        """Proportionally pan/tilt the gimbal to keep a detected face centered when tracking is on."""
        if offset is None:
            return
        now = time.monotonic()
        with self._lock:
            if not self._pose.get("tracking") or self._sleeping or self._estop_latched:
                return
            if (now - self._last_track_move_at) < 0.85:
                return
            dx, dy = offset
            if abs(dx) < 0.12 and abs(dy) < 0.12:
                return
            pan_step = max(-10.0, min(10.0, -dx * 24.0))
            tilt_step = max(-8.0, min(8.0, -dy * 18.0))
            new_pan = max(-145.0, min(145.0, round(float(self._pose["pan_deg"]) + pan_step, 1)))
            new_tilt = max(-60.0, min(60.0, round(float(self._pose["tilt_deg"]) + tilt_step, 1)))
            zoom = float(self._pose["zoom"])
            self._last_track_move_at = now
            self._pose["pan_deg"] = new_pan
            self._pose["tilt_deg"] = new_tilt
        self._dispatch_gimbal_hw(pan=new_pan, tilt=new_tilt, zoom=zoom)

    def _kill_active_stream_locked(self) -> None:
        proc = self._active_stream_proc
        self._active_stream_proc = None
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass

    def refresh_devices(self) -> dict[str, Any]:
        found = discover_host_peripherals(probe_system=True)
        with self._lock:
            self._devices = found
        self.sync_hardware_state()
        return dict(found)

    def read_gimbal_pose(self) -> dict[str, Any] | None:
        """Query live hardware gimbal pan/tilt/zoom via `droid-ptz info` on demand."""
        ptz = _resolve_droid_ptz()
        if not ptz:
            return None
        try:
            res = subprocess.run([ptz, "info"], capture_output=True, text=True, timeout=3.0, check=False)
            if res.returncode != 0:
                return None
            raw_out = res.stdout
            raw_text = raw_out.decode("utf-8", "replace") if isinstance(raw_out, bytes) else str(raw_out or "")
            data = json.loads(raw_text)
            if not isinstance(data, dict) or not data.get("ok"):
                return None
            cur = data.get("pantilt_cur")
            pan_arcsec: int | None = None
            tilt_arcsec: int | None = None
            if isinstance(cur, (list, tuple)) and len(cur) >= 2:
                pan_arcsec, tilt_arcsec = int(cur[0]), int(cur[1])
            elif isinstance(cur, str) and "," in cur:
                parts = cur.split(",", 1)
                pan_arcsec, tilt_arcsec = int(parts[0].strip()), int(parts[1].strip())
            elif isinstance(cur, dict) and "pan" in cur and "tilt" in cur:
                pan_arcsec, tilt_arcsec = int(cur["pan"]), int(cur["tilt"])
            if pan_arcsec is None or tilt_arcsec is None:
                return None
            zoom_raw = data.get("zoom_cur")
            zoom = round(float(zoom_raw) / 100.0, 2) if zoom_raw is not None else float(self._pose["zoom"])
            return {
                "pan_deg": round(pan_arcsec / UVC_ARCSEC_PER_DEG, 2),
                "tilt_deg": round(tilt_arcsec / UVC_ARCSEC_PER_DEG, 2),
                "zoom": zoom,
                "pan_arcsec": pan_arcsec,
                "tilt_arcsec": tilt_arcsec,
                "raw": data,
            }
        except Exception:  # noqa: BLE001
            return None

    def observe(self) -> Mapping[str, Any]:
        with self._lock:
            camera_state = (
                "parked"
                if self._sleeping
                else ("streaming" if self._active_stream_proc is not None else "ready")
            )
            return {
                "embodiment": self.name,
                "awake": not self._sleeping,
                "sleeping": self._sleeping,
                "camera": camera_state,
                "paused": self._paused,
                "estop_latched": self._estop_latched,
                "estop_reason": self._estop_reason,
                "pose": dict(self._pose),
                "devices": dict(self._devices),
                "vision": self._vision.stats() if self._vision is not None else None,
                "voice_enrolled": self._voice_enrolled(),
                "action_count": self._action_count,
                "last_capture_at": self._last_capture_at,
                "reflex": self.reflex.status(),
            }

    def sleep(self, reason: str = "operator") -> dict[str, Any]:
        """Fail-safe privacy park: stop live camera and tilt lens downward. NEVER blocked by E-Stop."""
        with self._lock:
            self._sleeping = True
            self._paused = True
            self._pose["tracking"] = False
            self._kill_active_stream_locked()
            self._action_count += 1
            self._pose.update({"pan_deg": self.PARK_PAN_DEG, "tilt_deg": self.PARK_TILT_DEG, "zoom": 1.0})
            hw_dispatched = self._dispatch_gimbal_hw(pan=self.PARK_PAN_DEG, tilt=self.PARK_TILT_DEG, zoom=1.0)
            return {
                "ok": True,
                "action": "sleep",
                "awake": False,
                "sleeping": True,
                "camera": "parked",
                "reason": reason,
                "pose": dict(self._pose),
                "hardware_dispatched": hw_dispatched,
            }

    def wake(self, reason: str = "operator") -> dict[str, Any]:
        """Wake Droid and center gimbal. Blocked fail-closed whenever E-Stop is latched."""
        with self._lock:
            if self._estop_latched:
                return {
                    "ok": False,
                    "error": f"estop_latched:{self._estop_reason}",
                    "awake": False,
                    "sleeping": self._sleeping,
                }
            self._sleeping = False
            self._paused = False
            self._action_count += 1
            self.reflex.touch(f"wake:{reason}")
            self._pose.update({"pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0})
            hw_dispatched = self._dispatch_gimbal_hw(pan=0.0, tilt=0.0, zoom=1.0, reset=True)
            return {
                "ok": True,
                "action": "wake",
                "awake": True,
                "sleeping": False,
                "camera": "ready",
                "reason": reason,
                "pose": dict(self._pose),
                "hardware_dispatched": hw_dispatched,
            }

    def capture_frame(self, *, device_index: str = "0", summary: str = "", include_preview: bool = False) -> dict[str, Any]:
        """Capture a single JPEG frame via macOS AVFoundation ffmpeg into RollingFrameBuffer."""
        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            if self._sleeping:
                return {"ok": False, "error": "droid_sleeping"}
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
                    "1280x720",
                    "-i",
                    f"{device_index}:none",
                    "-vf",
                    "scale=640:-2",
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
        result = {"ok": True, "frame": meta}
        if include_preview:
            result["preview"] = base64.b64encode(raw).decode("ascii")
        return result

    async def stream_camera(self) -> AsyncIterator[bytes]:
        """Read a continuous, bounded MJPEG feed from the host camera."""
        with self._lock:
            if self._estop_latched or self._sleeping:
                return
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is unavailable")
        proc = await asyncio.create_subprocess_exec(
            ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
            "-framerate", "30", "-video_size", "1280x720", "-i", "0:none",
            "-vf", "fps=12,scale=640:-2", "-c:v", "mjpeg", "-f", "image2pipe", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        aborted = False
        with self._lock:
            if self._estop_latched or self._sleeping:
                aborted = True
            else:
                self._active_stream_proc = proc
        if aborted:
            if proc.returncode is None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
            await proc.communicate()
            return
        assert proc.stdout is not None
        from .person_overlay import PersonOverlay
        overlay = PersonOverlay()
        buffer = bytearray()
        try:
            while chunk := await asyncio.wait_for(proc.stdout.read(65536), timeout=6):
                with self._lock:
                    if self._estop_latched or self._sleeping:
                        return
                buffer.extend(chunk)
                while (end := buffer.find(b"\xff\xd9")) >= 0:
                    frame = bytes(buffer[:end + 2])
                    del buffer[:end + 2]
                    with self._lock:
                        if self._estop_latched or self._sleeping:
                            return
                        if frame.startswith(b"\xff\xd8"):
                            if self._vision is not None:
                                self._vision.push_frame(frame, source="host_cam:0")
                            self._last_capture_at = time.time()
                    if frame.startswith(b"\xff\xd8"):
                        rendered = await asyncio.to_thread(overlay.render, frame)
                        if self._pose.get("tracking"):
                            await asyncio.to_thread(self._step_face_tracking, overlay.primary_face_offset())
                        yield rendered
                if len(buffer) > 2_000_000:
                    raise RuntimeError("Camera frame exceeds preview buffer")
        finally:
            with self._lock:
                if self._active_stream_proc is proc:
                    self._active_stream_proc = None
            if proc.returncode is None:
                try:
                    proc.kill()
                except (ProcessLookupError, OSError):
                    pass
            await proc.communicate()

    def act(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        p = dict(params or {})
        if action in ("sleep", "park"):
            return self.sleep(reason=str(p.get("reason") or "operator"))
        if action == "wake":
            return self.wake(reason=str(p.get("reason") or "operator"))

        with self._lock:
            if self._estop_latched:
                return {"ok": False, "error": f"estop_latched:{self._estop_reason}"}
            if action in ("look_at", "center", "track_person") and self._sleeping:
                return {"ok": False, "error": "droid_sleeping"}

            if action == "look_at":
                self._paused = False
                self._action_count += 1
                self.reflex.touch("look_at")
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
                self._paused = False
                self._action_count += 1
                self._pose.update({"pan_deg": 0.0, "tilt_deg": 0.0, "zoom": 1.0})
                hw_dispatched = self._dispatch_gimbal_hw(pan=0.0, tilt=0.0, zoom=1.0, reset=True)
                return {"ok": True, "action": action, "pose": dict(self._pose), "hardware_dispatched": hw_dispatched}
            if action == "track_person":
                self._paused = False
                self._action_count += 1
                enabled = bool(p.get("enabled", True))
                self._pose["tracking"] = enabled
                return {"ok": True, "action": action, "pose": dict(self._pose)}
            if action == "refresh_devices":
                self._action_count += 1
                return {"ok": True, "action": action, "devices": self.refresh_devices()}
            return {"ok": False, "error": f"unsupported_host_droid_action:{action}"}

    @staticmethod
    def _run_droid_ptz(cmd: list[str]) -> bool:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0, check=False)
        if res.returncode != 0:
            return False
        raw_out = res.stdout
        raw_text = raw_out.decode("utf-8", "replace").strip() if isinstance(raw_out, bytes) else str(raw_out or "").strip()
        if not raw_text:
            return True
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return False
        if isinstance(parsed, dict) and "ok" in parsed:
            return bool(parsed["ok"])
        return True

    def _dispatch_gimbal_hw(self, *, pan: float, tilt: float, zoom: float, reset: bool = False) -> bool:
        """Send real gimbal command via `droid-ptz` (preferred) or `linkctl` fallback if installed."""
        ptz = _resolve_droid_ptz()
        if ptz:
            pan_arcsec = int(round(pan * UVC_ARCSEC_PER_DEG))
            tilt_arcsec = int(round(tilt * UVC_ARCSEC_PER_DEG))
            zoom_val = max(100, min(400, int(round(zoom * 100))))
            last_zoom_val = max(100, min(400, int(round(self._last_dispatched_zoom * 100))))
            need_zoom = reset or (zoom_val != last_zoom_val)
            try:
                if not self._run_droid_ptz([ptz, "abs", str(pan_arcsec), str(tilt_arcsec)]):
                    return False
                if need_zoom:
                    if not self._run_droid_ptz([ptz, "zoom", str(zoom_val)]):
                        return False
                    self._last_dispatched_zoom = zoom_val / 100.0
                return True
            except Exception:  # noqa: BLE001
                return False

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
            self._kill_active_stream_locked()
            return {"ok": True, "estop_latched": True, "reason": reason}

    def release_estop(self) -> None:
        with self._lock:
            self._estop_latched = False
            self._estop_reason = ""


__all__ = ["PARK_PAN_DEG", "PARK_TILT_DEG", "HostDroidEmbodiment", "discover_host_peripherals"]
