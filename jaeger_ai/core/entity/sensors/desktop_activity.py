"""Safe Desktop Activity Sensor for Jaeger (ProactiveAgent reference pattern).

Monitors high-level desktop and workspace context:
- User idle seconds
- Active foreground application name (safe metadata only)
- Active workspace path
- System load and resource state

Strict Security & Privacy Controls:
- NO keylogging
- NO screen grabbing or OCR without explicit operator action
- NO capture of sensitive windows (password managers, private browsing)
- Fully permission-gated
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from typing import Any, Sequence

from jaeger_ai.core.entity.events import JaegerEvent
from .base import SensorAdapter

logger = logging.getLogger("jaeger.entity.sensors.desktop")


class DesktopActivitySensor(SensorAdapter):
    """Gathers safe desktop context metadata without privacy intrusion."""

    def __init__(
        self,
        workspace_path: str = "",
        enabled: bool = True,
        idle_threshold_s: float = 300.0,
    ) -> None:
        super().__init__(sensor_id="desktop_activity", enabled=enabled)
        self.workspace_path = workspace_path or os.getcwd()
        self.idle_threshold_s = idle_threshold_s
        self._last_active_ts = time.time()

    def record_activity(self) -> None:
        """Call when user interacts with the system."""
        self._last_active_ts = time.time()

    def _get_active_app(self) -> str:
        """Retrieve the frontmost application name safely on macOS."""
        # Optional PyObjC inspection if available; otherwise safe fallback
        try:
            from AppKit import NSWorkspace  # type: ignore[import-not-found]
            active_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if active_app:
                name = str(active_app.localizedName() or "")
                # Privacy filter: redact password managers or sensitive apps
                if any(p in name.lower() for p in ("1password", "bitwarden", "keychain")):
                    return "[protected]"
                return name
        except Exception:
            pass
        return "Terminal" if os.environ.get("TERM") else "Unknown"

    def _get_disk_telemetry(self) -> tuple[float, float]:
        try:
            usage = shutil.disk_usage(self.workspace_path)
            return round(usage.free / (1024**3), 2), round(usage.total / (1024**3), 2)
        except Exception:
            return 0.0, 0.0

    def poll(self) -> Sequence[JaegerEvent]:
        if not self.enabled:
            return []

        now = time.time()
        idle_s = max(0.0, now - self._last_active_ts)
        active_app = self._get_active_app()
        free_gb, total_gb = self._get_disk_telemetry()

        alerts: list[str] = []
        salience = 0.2  # Routine passive telemetry

        if free_gb < 2.0:
            alerts.append(f"Disk free space critically low: {free_gb} GB")
            salience = 0.9

        signals: dict[str, Any] = {
            "active_app": active_app,
            "idle_seconds": round(idle_s, 1),
            "disk_free_gb": free_gb,
            "disk_total_gb": total_gb,
            "focus": os.path.basename(self.workspace_path),
            "alerts": alerts,
        }

        event = JaegerEvent.perception_sensed(
            sensor=self.sensor_id,
            signals=signals,
            salience=salience,
        )
        return [event]
