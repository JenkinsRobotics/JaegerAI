"""Droid Mode 2-Tier Reflex & Privacy Auto-Park Controller (0 LLM tokens, 0 GPU).

Mirrors the fast-reflex / slow-brain architecture of Mindcraft for physical Droid Mode:
- Tracks last owner presence / voice / camera interaction timestamp
- Automatically parks the motorized gimbal (-85 deg privacy park) and puts Droid
  to sleep after configurable idle timeout when no owner interaction occurs
- Immediately halts and parks on global E-Stop
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping


class DroidReflexController:
    """Lightweight background reflex loop for privacy-first Droid Mode presence."""

    def __init__(
        self,
        *,
        is_awake: Callable[[], bool],
        is_estop: Callable[[], bool],
        sleep_fn: Callable[[], Any],
        on_event: Callable[[str, Mapping[str, Any]], None] | None = None,
        auto_park_enabled: bool = True,
        idle_park_s: float = 600.0,
        check_interval_s: float = 15.0,
    ) -> None:
        self._is_awake = is_awake
        self._is_estop = is_estop
        self._sleep_fn = sleep_fn
        self._on_event = on_event
        self._lock = threading.RLock()
        self._auto_park_enabled = bool(auto_park_enabled)
        self._idle_park_s = max(30.0, min(float(idle_park_s), 3600.0))
        self._check_interval_s = max(1.0, float(check_interval_s))
        self._last_interaction_at = time.time()
        self._last_interaction_reason = "init"
        self._auto_park_count = 0
        self._last_auto_park_at = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def touch(self, reason: str = "interaction", *, now: float | None = None) -> None:
        with self._lock:
            self._last_interaction_at = float(now if now is not None else time.time())
            self._last_interaction_reason = str(reason or "interaction")[:60]

    def update_config(
        self,
        *,
        auto_park_enabled: bool | None = None,
        idle_park_s: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if auto_park_enabled is not None:
                self._auto_park_enabled = bool(auto_park_enabled)
            if idle_park_s is not None:
                self._idle_park_s = max(30.0, min(float(idle_park_s), 3600.0))
        return self.status()

    def status(self, *, now: float | None = None) -> dict[str, Any]:
        ts = float(now if now is not None else time.time())
        with self._lock:
            idle_s = max(0.0, ts - self._last_interaction_at)
            remaining = max(0.0, self._idle_park_s - idle_s) if self._auto_park_enabled else None
            return {
                "auto_park_enabled": self._auto_park_enabled,
                "idle_park_s": int(self._idle_park_s),
                "idle_elapsed_s": round(idle_s, 1),
                "park_in_s": round(remaining, 1) if remaining is not None else None,
                "last_interaction_reason": self._last_interaction_reason,
                "auto_park_count": self._auto_park_count,
                "last_auto_park_at": self._last_auto_park_at or None,
                "running": bool(self._thread is not None and self._thread.is_alive()),
            }

    def evaluate_once(self, *, now: float | None = None) -> dict[str, Any]:
        """Single deterministic reflex tick (safe to call from unit tests or timer)."""
        ts = float(now if now is not None else time.time())
        if self._is_estop():
            return {"acted": False, "reason": "estop"}
        if not self._is_awake():
            return {"acted": False, "reason": "already_asleep"}
        with self._lock:
            enabled = self._auto_park_enabled
            threshold = self._idle_park_s
            idle_s = max(0.0, ts - self._last_interaction_at)
        if not enabled:
            return {"acted": False, "reason": "auto_park_disabled"}
        if idle_s < threshold:
            return {"acted": False, "reason": "within_idle_window", "idle_s": round(idle_s, 1)}
        # Auto-park privacy reflex triggered
        self._sleep_fn()
        with self._lock:
            self._auto_park_count += 1
            self._last_auto_park_at = ts
        if self._on_event is not None:
            try:
                self._on_event(
                    "droid.auto_parked",
                    {"idle_s": round(idle_s, 1), "idle_park_s": int(threshold), "timestamp": ts},
                )
            except Exception:  # noqa: BLE001
                pass
        return {"acted": True, "action": "auto_park_sleep", "idle_s": round(idle_s, 1)}

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="jaeger-droid-reflex",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def _run_loop(self) -> None:
        while not self._stop.wait(self._check_interval_s):
            try:
                self.evaluate_once()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["DroidReflexController"]
