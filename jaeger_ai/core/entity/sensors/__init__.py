"""Sensor adapters package for Jaeger Entity."""

from .base import SensorAdapter
from .desktop_activity import DesktopActivitySensor

__all__ = ["DesktopActivitySensor", "SensorAdapter"]
