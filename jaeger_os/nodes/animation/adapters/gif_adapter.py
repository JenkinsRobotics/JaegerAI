"""GifAdapter — L3 GIF animation level.

Pillow-based decoder; works with animated GIF + APNG (Pillow handles
both through the same iterator API).  Each source frame is fit to
the target size + converted to RGBA8 once at ``open()``; ``next_frame()``
walks the cached frames using per-frame durations from the source.

Architecture vendored from Mochi
─────────────────────────────────
Distilled from Mochi's ``GifHandler`` + ``decoders/gif_decoder.py``
+ ``media_base.py`` chain.  Simplified to the JROS Protocol:
open / close / next_frame.  Loop semantics handled by walking
elapsed time mod total_duration.  Apache 2.0; see
``dev/docs/library_review/mochi_demo.md`` for the audit.

Skill tree
──────────
``skill_id = "animation.gif"``, ``level = 3``.  Prereqs include
``animation.image`` mastered (operator-tunable in registry).
Mastering this unlocks ``animation.video`` (L4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageSequence

from ..base import FrameBuffer
from .image_adapter import _fit_contain, _fit_cover  # vendored helpers


@dataclass
class _CachedFrame:
    """One decoded source frame, target-sized, RGBA8."""
    pixels: bytes
    duration_ms: int


class GifAdapter:
    """Play an animated GIF/APNG asset, looping by default."""

    skill_id: str = "animation.gif"
    level: int = 3

    def __init__(self) -> None:
        self._frames: list[_CachedFrame] = []
        self._total_duration_ms: int = 0
        self._width: int = 0
        self._height: int = 0
        self._loop: bool = True
        self._start_time: float | None = None

    # ── Protocol surface ──────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Decode + cache every source frame at the target size.

        ``params``:
          ``fit``           "contain" (default), "cover", "fill"
          ``letterbox_rgb`` (r, g, b) for letterbox bands; default black
          ``loop``          True (default) plays forever; False plays
                            one pass then returns None
        """
        p = dict(params or {})
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        self._loop = bool(p.get("loop", True))
        fit = str(p.get("fit", "contain")).lower()
        letterbox_rgb = tuple(p.get("letterbox_rgb", (0, 0, 0)))
        self._frames = _decode_animated(
            asset_path,
            target=(self._width, self._height),
            fit=fit,
            letterbox_rgb=letterbox_rgb,
        )
        self._total_duration_ms = sum(f.duration_ms for f in self._frames)
        self._start_time = None

    def close(self) -> None:
        self._frames = []
        self._total_duration_ms = 0
        self._start_time = None

    def next_frame(self, t: float) -> FrameBuffer | None:
        if not self._frames:
            return None
        if self._start_time is None:
            self._start_time = t
        elapsed_ms = max(0, int((t - self._start_time) * 1000.0))
        if not self._loop and elapsed_ms >= self._total_duration_ms:
            return None
        if self._total_duration_ms > 0:
            elapsed_ms %= self._total_duration_ms
        # Walk per-frame durations to find the active frame.
        acc = 0
        idx = 0
        for i, fr in enumerate(self._frames):
            dur = fr.duration_ms if fr.duration_ms > 0 else 100
            if elapsed_ms < acc + dur:
                idx = i
                break
            acc += dur
        else:
            idx = len(self._frames) - 1
        chosen = self._frames[idx]
        return FrameBuffer(
            width=self._width,
            height=self._height,
            data=chosen.pixels,
            duration_ms=chosen.duration_ms,
            is_final=False,
        )


# ── helpers ───────────────────────────────────────────────────────

def _decode_animated(
    asset_path: str,
    *,
    target: tuple[int, int],
    fit: str,
    letterbox_rgb: tuple[int, int, int],
) -> list[_CachedFrame]:
    """Walk every source frame via Pillow's ImageSequence; convert
    each to the target size + RGBA8."""
    target_w, target_h = target
    cached: list[_CachedFrame] = []
    with Image.open(asset_path) as src:
        for frame in ImageSequence.Iterator(src):
            rgba = frame.convert("RGBA")
            if fit == "cover":
                fitted = _fit_cover(rgba, target_w, target_h)
            elif fit == "fill":
                fitted = rgba.resize((target_w, target_h), Image.LANCZOS)
            else:
                fitted = _fit_contain(
                    rgba, target_w, target_h, letterbox_rgb,
                )
            duration_ms = int(frame.info.get("duration", 100) or 100)
            cached.append(_CachedFrame(
                pixels=fitted.tobytes(),
                duration_ms=duration_ms,
            ))
    return cached
