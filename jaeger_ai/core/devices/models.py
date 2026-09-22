"""Device and Node Architecture Domain Models (Workstream 13).

Provides generic abstraction for Macs, Phones, Web clients, Vision Pro,
sensors, and future robotic embodiments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any
import uuid

from jaeger_ai.contract.schemas import Device


class DeviceCapability(str, Enum):
    DISPLAY = "display"
    MICROPHONE = "microphone"
    SPEAKER = "speaker"
    CAMERA = "camera"
    LOCATION = "location"
    FILESYSTEM = "filesystem"
    COMPUTE = "compute"
    MOTION = "motion"
    LIGHTING = "lighting"
    SENSORS = "sensors"


class DeviceType(str, Enum):
    MAC = "mac"
    WEB = "web"
    PHONE = "phone"
    VISION_PRO = "vision_pro"
    ROBOT = "robot"
    SENSOR = "sensor"
    CLI = "cli"


@dataclass(frozen=True)
class DevicePairingSecret:
    """Pairing credential issued upon initial device authorization."""
    device_id: str
    secret_token: str
    issued_at: float = field(default_factory=time.time)
    is_revoked: bool = False


@dataclass
class DeviceTelemetry:
    """Live telemetry reported during device heartbeats."""
    battery_level: float | None = None  # 0.0 - 1.0
    cpu_usage: float | None = None      # 0.0 - 1.0
    memory_free_bytes: int | None = None
    sensor_readings: dict[str, Any] = field(default_factory=dict)
    reported_at: float = field(default_factory=time.time)
