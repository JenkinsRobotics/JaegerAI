"""Sensor adapters package for Jaeger Entity."""

from .base import SensorAdapter
from .desktop_activity import DesktopActivitySensor
from .tiered import (
    PerceptionTier,
    TieredObservation,
    TieredPerceptionCoordinator,
)

__all__ = [
    "DesktopActivitySensor",
    "PerceptionTier",
    "SensorAdapter",
    "TieredObservation",
    "TieredPerceptionCoordinator",
]
