"""VideoAdapter — our custom video decoder, producing RGBA frames.

Wraps imageio (ffmpeg) into the same FrameBuffer adapter protocol the image
and gif adapters use, so video flows through the one frame pipeline the media
node streams on the bus. Decode-by-index is simple, not the fastest; a
streaming reader is a later optimization.
"""

from __future__ import annotations

from typing import Any

from ..frames import FrameBuffer


class VideoAdapter:
    skill_id: str = "media.video"
    level: int = 4

    def __init__(self) -> None:
        self._reader: Any = None
        self._w = 0
        self._h = 0
        self._fps = 25.0
        self._n = 0
        self._loop = True

    def open(self, asset_path: str, *, width: int, height: int, params: dict) -> None:
        import imageio
        self._w, self._h = width, height
        self._loop = bool((params or {}).get("loop", True))
        self._reader = imageio.get_reader(asset_path)  # ffmpeg backend
        meta = self._reader.get_meta_data() or {}
        self._fps = float(meta.get("fps", 25.0)) or 25.0
        try:
            self._n = int(self._reader.count_frames())
        except Exception:  # noqa: BLE001 — some containers can't count; fall back
            self._n = int(meta.get("nframes", 0) or 0)

    def next_frame(self, t: float) -> FrameBuffer | None:
        if self._reader is None:
            return None
        i = int(t * self._fps)
        if self._n and i >= self._n:
            if not self._loop:
                return None
            i %= self._n
        try:
            arr = self._reader.get_data(i)  # (H, W, 3) RGB uint8
        except (IndexError, StopIteration):
            return None
        return FrameBuffer(width=self._w, height=self._h, data=self._to_rgba(arr),
                           duration_ms=int(1000.0 / self._fps))

    def _to_rgba(self, arr: Any) -> bytes:
        from PIL import Image
        img = Image.fromarray(arr).convert("RGBA")
        if (img.width, img.height) != (self._w, self._h):
            img = img.resize((self._w, self._h), Image.BILINEAR)
        return img.tobytes()

    def close(self) -> None:
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:  # noqa: BLE001
                pass
            self._reader = None
