"""Native macOS AVFoundation media capture for Insta360 Link 2.

Handles:
  1. High-resolution visual snapshots ("eyes") from the 4K camera.
  2. High-fidelity audio sample recordings ("ears") from the beamforming microphone array.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .constants import (
    AUDIO_DEVICE_NAME,
    CAMERA_DEVICE_NAME,
)
from .contracts import AudioSample, CameraFrame


class MediaCaptureError(RuntimeError):
    pass


class AVFoundationCapture:
    """Manages audio and video capture through macOS AVFoundation."""

    def __init__(
        self,
        camera_name: str = CAMERA_DEVICE_NAME,
        audio_name: str = AUDIO_DEVICE_NAME,
        ffmpeg_bin: str | None = None,
    ):
        self.camera_name = camera_name
        self.audio_name = audio_name
        self.ffmpeg_bin = ffmpeg_bin or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        if not os.path.exists(self.ffmpeg_bin):
            raise FileNotFoundError(f"ffmpeg binary not found at {self.ffmpeg_bin}")

    def get_device_indices(self) -> tuple[int | None, int | None]:
        """Query AVFoundation device list and return (video_index, audio_index)."""
        cmd = [self.ffmpeg_bin, "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = proc.stderr

        video_idx: int | None = None
        audio_idx: int | None = None

        in_video = False
        in_audio = False

        for line in output.splitlines():
            if "AVFoundation video devices:" in line:
                in_video = True
                in_audio = False
                continue
            elif "AVFoundation audio devices:" in line:
                in_video = False
                in_audio = True
                continue

            if in_video:
                match = re.search(r"\[(\d+)\]\s+(.*)", line)
                if match:
                    idx, name = int(match.group(1)), match.group(2).strip()
                    if self.camera_name.lower() in name.lower():
                        video_idx = idx
            elif in_audio:
                match = re.search(r"\[(\d+)\]\s+(.*)", line)
                if match:
                    idx, name = int(match.group(1)), match.group(2).strip()
                    if self.audio_name.lower() in name.lower():
                        audio_idx = idx

        # Fallback to index 1 if detected previously
        return video_idx if video_idx is not None else 1, audio_idx if audio_idx is not None else 1

    def capture_frame(
        self,
        output_path: Path | None = None,
        resolution: str = "1920x1080",
    ) -> CameraFrame:
        """Capture a single image frame from the Insta360 Link 2."""
        v_idx, _ = self.get_device_indices()
        if v_idx is None:
            raise MediaCaptureError(f"Camera '{self.camera_name}' not detected")

        if output_path is None:
            output_path = Path("/tmp") / f"jaeger_frame_{int(time.time()*1000)}.jpg"
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        input_spec = f"{v_idx}:none"
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f", "avfoundation",
            "-framerate", "30",
            "-video_size", resolution,
            "-i", input_spec,
            "-vframes", "1",
            str(output_path),
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                raise MediaCaptureError(f"Frame capture failed (exit code {res.returncode}): {res.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            raise MediaCaptureError("Frame capture timed out after 8s")

        # Parse resolution integers
        try:
            w, h = (int(x) for x in resolution.split("x"))
        except (TypeError, ValueError):
            w, h = 1920, 1080

        return CameraFrame(
            path=output_path,
            width=w,
            height=h,
            format=output_path.suffix.lstrip(".").lower() or "jpg",
            timestamp=time.time(),
            device_name=self.camera_name,
        )

    def record_audio(
        self,
        duration_seconds: float = 3.0,
        output_path: Path | None = None,
        sample_rate: int = 48000,
    ) -> AudioSample:
        """Record audio clip from the Insta360 Link 2 beamforming microphone."""
        _, a_idx = self.get_device_indices()
        if a_idx is None:
            raise MediaCaptureError(f"Audio device '{self.audio_name}' not detected")

        if output_path is None:
            output_path = Path("/tmp") / f"jaeger_audio_{int(time.time()*1000)}.wav"
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        input_spec = f"none:{a_idx}"
        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-f", "avfoundation",
            "-i", input_spec,
            "-ar", str(sample_rate),
            "-ac", "1",
            "-t", str(duration_seconds),
            str(output_path),
        ]

        timeout_budget = duration_seconds + 5.0
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_budget,
                check=False,
            )
            if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                raise MediaCaptureError(f"Audio recording failed (exit code {res.returncode}): {res.stderr[-300:]}")
        except subprocess.TimeoutExpired:
            raise MediaCaptureError(f"Audio recording timed out after {timeout_budget}s")

        return AudioSample(
            path=output_path,
            duration_seconds=duration_seconds,
            sample_rate=sample_rate,
            channels=1,
            format=output_path.suffix.lstrip(".").lower() or "wav",
            timestamp=time.time(),
            device_name=self.audio_name,
        )
