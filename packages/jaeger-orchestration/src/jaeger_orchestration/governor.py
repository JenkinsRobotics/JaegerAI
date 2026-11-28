"""32 GB Apple Silicon Resource Governor & 3-Tier Owner-First Priority Scheduler.

Enforces two critical invariants for a 24/7 single-machine AI companion & droid:
1. **Single-Heavy-Model-at-a-Time Residency:** Ensures heavy local LLMs / VLMs
   never collide and OOM a 32 GB unified-memory host.
2. **Owner-First Preemption (`OWNER_WORK > AWARENESS_SAFETY > IDLE_LIFE`):**
   Idle autonomy (e.g. headless Minecraft persistence) ONLY runs when the owner
   is idle past cooldown. The instant Tier 1 Owner Work arrives, all registered
   idle preemption hooks fire immediately to checkpoint state and yield 100% of
   compute to the owner.
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable


class PriorityTier(IntEnum):
    OWNER_WORK = 1
    AWARENESS_SAFETY = 2
    IDLE_LIFE = 3


def _probe_host_memory_gb() -> tuple[float, float]:
    """Return ``(total_gb, available_gb)`` with zero external dependencies."""
    total_gb = 32.0
    avail_gb = 16.0
    try:
        if platform.system() == "Darwin":
            raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=1.0).strip()
            total_gb = round(int(raw) / (1024**3), 2)
            vm = subprocess.check_output(["vm_stat"], text=True, timeout=1.0)
            page_size = 16384
            free_pages = 0
            inactive_pages = 0
            speculative_pages = 0
            for ln in vm.splitlines():
                if "page size of" in ln:
                    parts = ln.split("page size of", 1)[1].strip().split()
                    if parts and parts[0].isdigit():
                        page_size = int(parts[0])
                elif ln.startswith("Pages free:"):
                    free_pages = int(ln.split(":", 1)[1].strip().rstrip("."))
                elif ln.startswith("Pages inactive:"):
                    inactive_pages = int(ln.split(":", 1)[1].strip().rstrip("."))
                elif ln.startswith("Pages speculative:"):
                    speculative_pages = int(ln.split(":", 1)[1].strip().rstrip("."))
            avail_gb = round(((free_pages + inactive_pages + speculative_pages) * page_size) / (1024**3), 2)
        elif os.path.isfile("/proc/meminfo"):
            info: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8") as f:
                for ln in f:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        toks = v.strip().split()
                        if toks and toks[0].isdigit():
                            info[k] = int(toks[0])
            if "MemTotal" in info:
                total_gb = round(info["MemTotal"] / (1024**2), 2)
            if "MemAvailable" in info:
                avail_gb = round(info["MemAvailable"] / (1024**2), 2)
    except Exception:  # noqa: BLE001
        pass
    return total_gb, avail_gb


@dataclass
class HeavyModelLease:
    model_id: str
    tier: PriorityTier
    owner_tag: str
    estimated_gb: float
    acquired_at: float = field(default_factory=time.time)


class ResourceGovernor:
    """Coordinates 32 GB model residency and Owner-First preemption across JaegerAI."""

    def __init__(
        self,
        *,
        memory_cap_gb: float = 24.0,
        idle_cooldown_s: float = 60.0,
        idle_life_enabled: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._memory_cap_gb = float(memory_cap_gb)
        self._idle_cooldown_s = float(idle_cooldown_s)
        self._idle_life_enabled = bool(idle_life_enabled)
        self._active_owner_runs = 0
        self._last_owner_activity_at = 0.0
        self._active_lease: HeavyModelLease | None = None
        self._preempt_hooks: list[Callable[[str], None]] = []
        self._preemption_count = 0
        self._estop_active = False

    def register_idle_preempt_hook(self, hook: Callable[[str], None]) -> None:
        """Register a callback invoked immediately when Tier 1 Owner Work preempts Tier 3 Idle Life."""
        with self._lock:
            self._preempt_hooks.append(hook)

    def set_idle_life_enabled(self, enabled: bool) -> None:
        hooks_to_call: list[Callable[[str], None]] = []
        with self._lock:
            self._idle_life_enabled = bool(enabled)
            if not enabled:
                hooks_to_call = list(self._preempt_hooks)
        for fn in hooks_to_call:
            try:
                fn("idle_life_disabled")
            except Exception:  # noqa: BLE001
                pass

    def trigger_estop(self, reason: str = "operator_estop") -> None:
        """Hardware/embodiment emergency stop — immediately halts idle autonomy and latches E-Stop."""
        hooks_to_call: list[Callable[[str], None]] = []
        with self._lock:
            self._estop_active = True
            self._idle_life_enabled = False
            hooks_to_call = list(self._preempt_hooks)
        for fn in hooks_to_call:
            try:
                fn(f"estop:{reason}")
            except Exception:  # noqa: BLE001
                pass

    def release_estop(self) -> None:
        with self._lock:
            self._estop_active = False

    def begin_owner_work(self, reason: str = "owner_request") -> None:
        """Enter Tier 1 Owner Work, preempting any Tier 3 idle autonomy immediately."""
        hooks_to_call: list[Callable[[str], None]] = []
        with self._lock:
            self._active_owner_runs += 1
            self._last_owner_activity_at = time.time()
            if self._active_lease is not None and self._active_lease.tier == PriorityTier.IDLE_LIFE:
                self._active_lease = None
                self._preemption_count += 1
                hooks_to_call = list(self._preempt_hooks)
            elif self._preempt_hooks:
                self._preemption_count += 1
                hooks_to_call = list(self._preempt_hooks)
        for fn in hooks_to_call:
            try:
                fn(reason)
            except Exception:  # noqa: BLE001
                pass

    def end_owner_work(self) -> None:
        with self._lock:
            self._active_owner_runs = max(0, self._active_owner_runs - 1)
            self._last_owner_activity_at = time.time()

    def can_run_idle_life(self, *, now: float | None = None) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for Tier 3 Idle Life (e.g. Minecraft)."""
        ts = time.time() if now is None else now
        with self._lock:
            if self._estop_active:
                return False, "estop_active"
            if not self._idle_life_enabled:
                return False, "idle_life_disabled"
            if self._active_owner_runs > 0:
                return False, "owner_work_active"
            elapsed = ts - self._last_owner_activity_at
            if self._last_owner_activity_at > 0 and elapsed < self._idle_cooldown_s:
                remaining = round(self._idle_cooldown_s - elapsed, 1)
                return False, f"owner_cooldown_{remaining}s"
            return True, "idle_ready"

    def acquire_heavy_model(
        self,
        model_id: str,
        *,
        tier: PriorityTier,
        owner_tag: str = "runtime",
        estimated_gb: float = 10.0,
    ) -> tuple[bool, str]:
        """Enforce single-heavy-model-at-a-time residency with strict priority preemption."""
        with self._lock:
            if tier == PriorityTier.IDLE_LIFE:
                ok, reason = self.can_run_idle_life()
                if not ok:
                    return False, reason
            if estimated_gb > self._memory_cap_gb:
                return False, f"exceeds_memory_cap_gb({estimated_gb}>{self._memory_cap_gb})"
            cur = self._active_lease
            if cur is not None and cur.model_id != model_id:
                if tier < cur.tier:
                    # Higher-priority work preempts lower-priority model slot
                    self._active_lease = HeavyModelLease(
                        model_id=model_id,
                        tier=tier,
                        owner_tag=owner_tag,
                        estimated_gb=estimated_gb,
                    )
                    self._preemption_count += 1
                    return True, f"preempted:{cur.model_id}"
                return False, f"busy_with:{cur.model_id}(tier={cur.tier.name})"
            self._active_lease = HeavyModelLease(
                model_id=model_id,
                tier=tier,
                owner_tag=owner_tag,
                estimated_gb=estimated_gb,
            )
            return True, "acquired"

    def release_heavy_model(self, model_id: str | None = None) -> None:
        with self._lock:
            if model_id is None or (self._active_lease and self._active_lease.model_id == model_id):
                self._active_lease = None

    def snapshot(self) -> dict[str, Any]:
        total_gb, avail_gb = _probe_host_memory_gb()
        with self._lock:
            idle_ok, idle_reason = self.can_run_idle_life()
            return {
                "host_total_gb": total_gb,
                "host_available_gb": avail_gb,
                "memory_cap_gb": self._memory_cap_gb,
                "active_owner_runs": self._active_owner_runs,
                "idle_life_enabled": self._idle_life_enabled,
                "idle_life_allowed_now": idle_ok,
                "idle_life_status": idle_reason,
                "estop_active": self._estop_active,
                "preemption_count": self._preemption_count,
                "active_heavy_model": (
                    {
                        "model_id": self._active_lease.model_id,
                        "tier": self._active_lease.tier.name,
                        "owner_tag": self._active_lease.owner_tag,
                        "estimated_gb": self._active_lease.estimated_gb,
                    }
                    if self._active_lease is not None
                    else None
                ),
            }


__all__ = ["HeavyModelLease", "PriorityTier", "ResourceGovernor"]
