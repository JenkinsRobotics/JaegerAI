"""Interfaces and data contracts for Jaeger's Insta360 feature."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CameraFrame:
    """Metadata and path for a captured camera snapshot."""
    path: Path
    width: int
    height: int
    format: str
    timestamp: float
    device_name: str


@dataclass
class AudioSample:
    """Metadata and path for a recorded audio sample."""
    path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    format: str
    timestamp: float
    device_name: str


@dataclass
class PTZPosition:
    """Pan, Tilt, Zoom coordinate snapshot."""
    pan: int
    tilt: int
    zoom: int | None = None
    tracking_enabled: bool | None = None


class BaseCameraAdapter(ABC):
    """Abstract interface for video/camera devices."""

    @abstractmethod
    def capture_frame(self, output_path: Path | None = None, resolution: str = "1920x1080") -> CameraFrame:
        """Capture a single still frame from the camera."""


class BaseAudioAdapter(ABC):
    """Abstract interface for microphone/audio input devices."""

    @abstractmethod
    def record_sample(self, duration_seconds: float = 3.0, output_path: Path | None = None) -> AudioSample:
        """Record an audio sample from the microphone."""


class BasePTZController(ABC):
    """Abstract interface for motorized pan/tilt/zoom and gimbal controls."""

    @abstractmethod
    def get_position(self) -> PTZPosition:
        """Read current gimbal pan/tilt/zoom position."""

    @abstractmethod
    def aim(self, pan: int, tilt: int) -> PTZPosition:
        """Orient gimbal to specific target coordinates."""

    @abstractmethod
    def center(self) -> PTZPosition:
        """Reset gimbal to default neutral center position."""
