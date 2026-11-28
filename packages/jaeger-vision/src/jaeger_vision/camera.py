"""24/7 camera awareness with hard rolling-frame memory pruning (smolagents pattern).

Keeps at most ``max_frames`` frames in memory (default 6) and drops older raw
image payloads deterministically so a 24/7 camera feed never bloats 32 GB RAM.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CameraFrame:
    frame_id: int
    source: str
    captured_at: float
    width: int
    height: int
    digest: str
    byte_size: int
    scene_changed: bool
    summary: str = ""
    raw_bytes: bytes = b""

    def to_metadata(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "source": self.source,
            "captured_at": self.captured_at,
            "width": self.width,
            "height": self.height,
            "digest": self.digest,
            "byte_size": self.byte_size,
            "scene_changed": self.scene_changed,
            "summary": self.summary,
        }


class RollingFrameBuffer:
    """Bounded FIFO ring buffer with scene-change detection and automatic old-frame pruning."""

    def __init__(self, *, max_frames: int = 6, max_total_mb: float = 24.0) -> None:
        self._max_frames = max(1, int(max_frames))
        self._max_total_bytes = int(max(1.0, float(max_total_mb)) * 1024 * 1024)
        self._lock = threading.RLock()
        self._frames: deque[CameraFrame] = deque()
        self._seq = 0
        self._last_digest = ""
        self._pruned_count = 0

    def push_frame(
        self,
        raw_bytes: bytes,
        *,
        source: str = "cam0",
        width: int = 640,
        height: int = 360,
        summary: str = "",
    ) -> CameraFrame:
        digest = hashlib.sha256(raw_bytes).hexdigest()[:16]
        with self._lock:
            self._seq += 1
            changed = digest != self._last_digest
            self._last_digest = digest
            frame = CameraFrame(
                frame_id=self._seq,
                source=source,
                captured_at=time.time(),
                width=width,
                height=height,
                digest=digest,
                byte_size=len(raw_bytes),
                scene_changed=changed,
                summary=summary,
                raw_bytes=raw_bytes,
            )
            self._frames.append(frame)
            self._prune_locked()
            return frame

    def _prune_locked(self) -> None:
        while len(self._frames) > self._max_frames:
            self._frames.popleft()
            self._pruned_count += 1
        while len(self._frames) > 1 and sum(f.byte_size for f in self._frames) > self._max_total_bytes:
            self._frames.popleft()
            self._pruned_count += 1

    def latest_frame(self) -> CameraFrame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def recent_metadata(self) -> list[dict[str, Any]]:
        with self._lock:
            return [f.to_metadata() for f in self._frames]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_bytes = sum(f.byte_size for f in self._frames)
            return {
                "resident_frames": len(self._frames),
                "max_frames": self._max_frames,
                "resident_mb": round(total_bytes / (1024 * 1024), 3),
                "total_ingested": self._seq,
                "pruned_count": self._pruned_count,
            }


__all__ = ["CameraFrame", "RollingFrameBuffer"]
