"""Background Sensor Supervisor & Live Producer (UPAA Principle 6).

Coordinates background polling of sensory adapters (e.g. DesktopActivitySensor)
through the TieredPerceptionCoordinator into the EntityRuntime Event Fabric.

Features:
- Thread-safe start / stop lifecycle
- Configurable polling interval
- Permission gate (defaults to disabled for privacy safety)
- Automated privacy redaction
- Robust failure isolation (sensor exceptions never crash the runtime)
- Ingestion into EntityRuntime -> SelfState reduction -> Salience evaluation
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from jaeger_ai.core.entity.events import JaegerEvent
from .base import SensorAdapter
from .desktop_activity import DesktopActivitySensor
from .tiered import TieredPerceptionCoordinator, redact_privacy_signals

logger = logging.getLogger("jaeger.entity.sensors.supervisor")


class SensorSupervisor:
    """Supervises periodic sensor polling in a background thread."""

    def __init__(
        self,
        runtime: Any = None,
        coordinator: TieredPerceptionCoordinator | None = None,
        sensor: SensorAdapter | None = None,
        *,
        interval_s: float = 10.0,
        enabled: bool = False,
        privacy_policy: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.coordinator = coordinator or TieredPerceptionCoordinator()
        self.sensor = sensor or DesktopActivitySensor(enabled=enabled)
        self.interval_s = max(0.1, interval_s)
        self.enabled = enabled
        self.privacy_policy = privacy_policy or redact_privacy_signals

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._poll_count = 0
        self._last_poll_ts = 0.0

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def poll_count(self) -> int:
        return self._poll_count

    def start(self) -> None:
        """Start the background polling supervisor if not already running."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="jaeger-sensor-supervisor",
            daemon=True,
        )
        self._thread.start()
        logger.info("SensorSupervisor started (interval=%.1fs, enabled=%s)", self.interval_s, self.enabled)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal stop and wait for background thread to exit."""
        if not self.is_running:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("SensorSupervisor stopped")

    def poll_once(self) -> JaegerEvent | None:
        """Execute a single polling cycle with failure isolation and ingestion."""
        if not self.enabled:
            return None

        try:
            # 1. Poll the raw sensor
            events = self.sensor.poll()
            if not events:
                return None

            raw_event = events[0]
            signals = raw_event.payload.get("signals") or raw_event.payload

            # 2. Apply privacy policy
            scrubbed_signals = self.privacy_policy(signals)

            # 3. Process through Tiered Perception
            observation = self.coordinator.process(self.sensor.sensor_id, scrubbed_signals)
            event = observation.to_event()

            # 4. Ingest into EntityRuntime
            rt = self.runtime
            if rt is None:
                from jaeger_ai.core.entity.runtime import EntityRuntime
                rt = EntityRuntime.get_singleton()

            rt.ingest(event)
            self._poll_count += 1
            self._last_poll_ts = time.time()
            return event
        except Exception as exc:
            # Failure isolation: logging warning without halting the supervisor
            logger.warning("SensorSupervisor poll cycle failed (isolated): %s", exc)
            return None

    def _run_loop(self) -> None:
        """Main periodic polling loop."""
        while not self._stop_event.is_set():
            if self.enabled:
                self.poll_once()
            # Wait for next interval or stop signal
            self._stop_event.wait(timeout=self.interval_s)
