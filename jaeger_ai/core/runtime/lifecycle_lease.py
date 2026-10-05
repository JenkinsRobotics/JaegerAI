"""Menu-bar ownership lease.

No lease file means one has not been issued yet, so this does not invent a
second owner. Once a lease exists, a missed heartbeat suspends privileged
work immediately. Controlled shutdown waits until the grace period. An
unreadable or foreign lease suspends and shuts down.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

_ENV = "JAEGER_LIFECYCLE_LEASE"
# The menu bar beats faster than this. One missed beat suspends; shutdown
# waits for the longer grace so a brief stall is not a stack teardown.
SUSPEND_AFTER_S = 5.0
SHUTDOWN_GRACE_S = 15.0


@dataclass(frozen=True)
class LeaseDecision:
    privileged_work_allowed: bool
    reason: str
    shutdown: bool = False


class LifecycleLease:
    def __init__(
        self,
        path: Path,
        *,
        grace_seconds: float = SHUTDOWN_GRACE_S,
        suspend_after: float | None = None,
    ) -> None:
        self.path = path
        self.grace_seconds = grace_seconds
        self.suspend_after = grace_seconds if suspend_after is None else suspend_after

    @classmethod
    def load(cls) -> LifecycleLease:
        raw = os.environ.get(_ENV, "").strip()
        if raw:
            path = Path(raw).expanduser()
        else:
            from jaeger_ai.core.instance.instance import operator_state_root
            path = operator_state_root() / "control" / "lifecycle-lease.json"
        return cls(path, grace_seconds=SHUTDOWN_GRACE_S, suspend_after=SUSPEND_AFTER_S)

    def beat(self, owner: str, *, now: float | None = None) -> None:
        if owner.strip() != "menubar":
            raise ValueError("the menu-bar app is the lifecycle owner")
        stamp = time.time() if now is None else now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps({"owner": "menubar", "beat_at": stamp}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    def decide(self, *, now: float | None = None) -> LeaseDecision:
        if not self.path.exists():
            return LeaseDecision(True, "no lease issued")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            beat_at = float(raw["beat_at"])
            if raw.get("owner") != "menubar":
                return LeaseDecision(False, "lifecycle lease is not the menu bar", shutdown=True)
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return LeaseDecision(False, "lifecycle lease is unreadable", shutdown=True)
        stamp = time.time() if now is None else now
        age = stamp - beat_at
        if age > self.grace_seconds:
            return LeaseDecision(False, "lifecycle owner disappeared", shutdown=True)
        if age > self.suspend_after:
            return LeaseDecision(False, "lifecycle owner heartbeat missed")
        return LeaseDecision(True, "lifecycle owner is alive")


def repairs_allowed() -> bool:
    """Workers may not resurrect Jaeger after the owner disappears or Stop latches.

    No lease file means the menu bar has not issued one yet, so boot is still
    allowed. A stale, foreign, or unreadable lease is not.
    """
    try:
        from jaeger_ai.core.gateway.global_stop import GlobalStop
        if GlobalStop.load().engaged():
            return False
    except Exception:
        return False
    try:
        return LifecycleLease.load().decide().privileged_work_allowed
    except Exception:
        return False
