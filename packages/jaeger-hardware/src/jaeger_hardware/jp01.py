"""JP01 physical droid embodiment implementing jaeger_contracts.EmbodimentPort."""

from __future__ import annotations

from typing import Any, Mapping

from .protocol import AsciiBracketProtocol
from .safety import EStopLatch


class JP01Embodiment:
    """Safe, clamped JP01 droid embodiment sharing EmbodimentPort with Minecraft."""

    name = "jp01_droid"

    def __init__(self, *, estop_latch: EStopLatch | None = None, dry_run: bool = True) -> None:
        self.latch = estop_latch or EStopLatch()
        self.protocol = AsciiBracketProtocol()
        self.dry_run = bool(dry_run)
        self._pose = {"pan_deg": 90, "tilt_deg": 90, "speed": 40}
        self._face_mood = "calm"
        self._tx_log: list[str] = []
        self.latch.register_stop("jp01_motion", lambda: self._tx_log.append("STOP\n"))

    def observe(self) -> Mapping[str, Any]:
        return {
            "embodiment": self.name,
            "dry_run": self.dry_run,
            "pose": dict(self._pose),
            "face_mood": self._face_mood,
            "estop": self.latch.status(),
            "tx_count": len(self._tx_log),
        }

    def act(self, action: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if self.latch.engaged:
            return {"ok": False, "error": self.latch.refusal()}
        p = dict(params or {})
        if action == "head_move":
            pan = max(30, min(150, int(p.get("pan_deg", self._pose["pan_deg"]))))
            tilt = max(45, min(135, int(p.get("tilt_deg", self._pose["tilt_deg"]))))
            speed = max(5, min(100, int(p.get("speed", self._pose["speed"]))))
            frame = self.protocol.encode({"header": "MJ", "args": [pan, tilt, speed]}).decode("utf-8")
            self._pose = {"pan_deg": pan, "tilt_deg": tilt, "speed": speed}
            self._tx_log.append(frame)
            return {"ok": True, "frame": frame.strip(), "pose": dict(self._pose), "dry_run": self.dry_run}
        if action == "face_expression":
            mood = str(p.get("mood") or "calm")
            frame = self.protocol.encode({"header": "FN", "payload": mood}).decode("utf-8")
            self._face_mood = mood
            self._tx_log.append(frame)
            return {"ok": True, "frame": frame.strip(), "face_mood": mood, "dry_run": self.dry_run}
        return {"ok": False, "error": f"unsupported_jp01_action:{action}"}

    def checkpoint(self) -> Mapping[str, Any]:
        return {"ok": True, "pose": dict(self._pose), "face_mood": self._face_mood}

    def pause(self, reason: str = "preempted") -> Mapping[str, Any]:
        return {"ok": True, "reason": reason, "pose": dict(self._pose)}

    def estop(self, reason: str = "operator") -> Mapping[str, Any]:
        self.latch.engage(reason, source="operator")
        return {"ok": True, "estop": self.latch.status()}


__all__ = ["JP01Embodiment"]
