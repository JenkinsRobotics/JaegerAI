"""Sensor adapters package for Jaeger Entity."""

from .base import SensorAdapter
from .desktop_activity import DesktopActivitySensor
from .supervisor import SensorSupervisor
from .tiered import (
    PerceptionTier,
    TieredObservation,
    TieredPerceptionCoordinator,
    redact_privacy_signals,
)

__all__ = [
    "DesktopActivitySensor",
    "PerceptionTier",
    "SensorAdapter",
    "SensorSupervisor",
    "TieredObservation",
    "TieredPerceptionCoordinator",
    "redact_privacy_signals",
]
