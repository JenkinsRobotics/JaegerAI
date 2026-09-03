"""Unified hardware adapter for Insta360 Link 2.

Serves as an optional Jaeger perception device:
  - Eyes: High-resolution visual snapshots for VLMs
  - Ears: Beamforming audio recordings for Whisper STT
  - Body: Motorized PTZ gimbal positioning, centering, and desk-view orientation
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .constants import (
    AUDIO_DEVICE_NAME,
    CAMERA_DEVICE_NAME,
    LINK2_PID,
    PAN_MAX,
    PAN_MIN,
    TILT_MAX,
    TILT_MIN,
)
from .contracts import (
    AudioSample,
    BaseAudioAdapter,
    BaseCameraAdapter,
    BasePTZController,
    CameraFrame,
    PTZPosition,
)
from .media_capture import AVFoundationCapture

logger = logging.getLogger("jaeger.features.insta360.link2")


class Insta360Link2(BaseCameraAdapter, BaseAudioAdapter, BasePTZController):
    """Integrated adapter providing Vision, Audition, and PTZ Gimbal control."""

    def __init__(
        self,
        camera_name: str = CAMERA_DEVICE_NAME,
        audio_name: str = AUDIO_DEVICE_NAME,
        pid: int = LINK2_PID,
    ):
        from .iokit_uvc import Link2GimbalIOKit

        self.camera_name = camera_name
        self.audio_name = audio_name
        self.pid = pid
        self._gimbal = Link2GimbalIOKit(pid=pid)
        self._media = AVFoundationCapture(camera_name=camera_name, audio_name=audio_name)

    # ── EYES (Camera) ─────────────────────────────────────────────────────────

    def capture_frame(
        self,
        output_path: Path | None = None,
        resolution: str = "1920x1080",
    ) -> CameraFrame:
        """Capture a visual snapshot from the Link 2 camera."""
        logger.info(f"Capturing frame at resolution {resolution}")
        return self._media.capture_frame(output_path=output_path, resolution=resolution)

    # ── EARS (Audio) ──────────────────────────────────────────────────────────

    def record_sample(
        self,
        duration_seconds: float = 3.0,
        output_path: Path | None = None,
    ) -> AudioSample:
        """Record an audio clip from the Link 2 microphone array."""
        logger.info(f"Recording audio sample for {duration_seconds}s")
        return self._media.record_audio(duration_seconds=duration_seconds, output_path=output_path)

    # ── BODY (Gimbal PTZ) ─────────────────────────────────────────────────────

    def get_position(self) -> PTZPosition:
        """Read live gimbal pan/tilt coordinates from the device."""
        pan, tilt = self._gimbal.read_pan_tilt()
        return PTZPosition(pan=pan, tilt=tilt)

    def aim(self, pan: int, tilt: int) -> PTZPosition:
        """Orient gimbal toward specific pan/tilt coordinates within safety limits."""
        bounded_pan = max(PAN_MIN, min(PAN_MAX, pan))
        bounded_tilt = max(TILT_MIN, min(TILT_MAX, tilt))
        logger.info(f"Aiming gimbal to pan={bounded_pan}, tilt={bounded_tilt}")
        self._gimbal.write_pan_tilt(pan=bounded_pan, tilt=bounded_tilt)
        return self.get_position()

    def center(self) -> PTZPosition:
        """Reset gimbal to dead center (pan=0, tilt=0)."""
        logger.info("Centering gimbal")
        return self.aim(pan=0, tilt=0)

    def deskview(self) -> PTZPosition:
        """Tilt down to inspect desk, keyboard, or paperwork."""
        logger.info("Setting gimbal to DeskView position")
        # Target -300,000 internal tilt units
        return self.aim(pan=0, tilt=-300000)

    # ── Diagnostics & Status ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Check overall hardware connection and return component health."""
        gimbal_ok = False
        pan = 0
        tilt = 0
        try:
            pos = self.get_position()
            gimbal_ok = True
            pan = pos.pan
            tilt = pos.tilt
        except (ConnectionError, OSError, RuntimeError, ValueError) as exc:
            logger.warning("Gimbal status check failed: %s", exc)

        v_idx, a_idx = self._media.get_device_indices()
        return {
            "device": "Insta360 Link 2",
            "connected": gimbal_ok or (v_idx is not None),
            "gimbal": {
                "available": gimbal_ok,
                "pan": pan,
                "tilt": tilt,
            },
            "video": {
                "device_name": self.camera_name,
                "avfoundation_index": v_idx,
            },
            "audio": {
                "device_name": self.audio_name,
                "avfoundation_index": a_idx,
            },
        }
