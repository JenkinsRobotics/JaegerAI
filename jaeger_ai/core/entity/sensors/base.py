"""Base Sensor Adapter Contract for Jaeger Entity (Pinocchio Architecture).

Follows the ProactiveAgent / ActivityWatch architectural separation:
external sensor signals ──► SensorAdapter ──► JaegerEvent ──► EntityRuntime
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from jaeger_ai.core.entity.events import JaegerEvent


class SensorAdapter(ABC):
    """Abstract base adapter for environmental, OS, and hardware sensors."""

    def __init__(self, sensor_id: str, enabled: bool = True) -> None:
        self.sensor_id = sensor_id
        self.enabled = enabled

    @abstractmethod
    def poll(self) -> Sequence[JaegerEvent]:
        """Poll the sensor and produce zero or more normalized JaegerEvents."""
        raise NotImplementedError
