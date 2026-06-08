"""BitmapAdapter — L1 STATIC animation level (1-bit monochrome).

Renders a 1-bit packed bitmap from a JSON asset:

  {
    "width":  16,
    "height": 16,
    "data":   [0x18, 0x18, 0x3C, ... ]    // packed MSB-first
  }

Each byte holds 8 bits, packed most-significant-bit-first (Adafruit
GFX style).  Rows are padded to whole bytes.  ON pixels get the
adapter's foreground colour; OFF pixels get the background.

Architecture vendored from Mochi
─────────────────────────────────
Distilled from Mochi's BitmapHandler (Apache 2.0; see
``dev_docs/library_review/mochi_demo.md``).  Reshaped to the JROS
Protocol + RGBA8 output; the numpy unpacking is preserved
verbatim because it's already cleanly vectorised.

Skill tree
──────────
``skill_id = "animation.bitmap"``, ``level = 1``.  Sibling of
``animation.image``; both are L1 STATIC.  Mastering either
contributes toward unlocking L2 sprite adapters.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..base import FrameBuffer


class BitmapAdapter:
    """Render a single 1-bit bitmap, centred on the canvas."""

    skill_id: str = "animation.bitmap"
    level: int = 1

    def __init__(self) -> None:
        self._buffer: bytes = b""
        self._width: int = 0
        self._height: int = 0
        self._emitted: bool = False

    # ── Protocol surface ──────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Load + render the bitmap once into the cached RGBA buffer.

        ``params``:
          ``fg_rgb`` (r, g, b) — ON pixel colour; default white
          ``bg_rgb`` (r, g, b) — OFF pixel colour; default black
        """
        p = dict(params or {})
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        fg = tuple(p.get("fg_rgb", (255, 255, 255)))
        bg = tuple(p.get("bg_rgb", (0, 0, 0)))
        self._buffer = _render_bitmap(
            asset_path,
            target=(self._width, self._height),
            fg_rgb=fg, bg_rgb=bg,
        )
        self._emitted = False

    def close(self) -> None:
        self._buffer = b""
        self._emitted = False

    def next_frame(self, t: float) -> FrameBuffer | None:
        if not self._buffer or self._emitted:
            return None
        self._emitted = True
        return FrameBuffer(
            width=self._width,
            height=self._height,
            data=self._buffer,
            duration_ms=0,
            is_final=True,
        )


# ── helpers ───────────────────────────────────────────────────────

def _render_bitmap(
    asset_path: str,
    *,
    target: tuple[int, int],
    fg_rgb: tuple[int, int, int],
    bg_rgb: tuple[int, int, int],
) -> bytes:
    """Load the JSON bitmap and produce an RGBA8 buffer
    ``target.w * target.h * 4`` bytes long, centred."""
    payload = json.loads(Path(asset_path).read_text())
    bw = int(payload.get("width", 0))
    bh = int(payload.get("height", 0))
    raw = payload.get("data", [])

    target_w, target_h = target
    frame = np.empty((target_h, target_w, 4), dtype=np.uint8)
    frame[..., 0] = bg_rgb[0]
    frame[..., 1] = bg_rgb[1]
    frame[..., 2] = bg_rgb[2]
    frame[..., 3] = 255

    if not raw or bw <= 0 or bh <= 0:
        return frame.tobytes()

    data = np.array(raw, dtype=np.uint8)
    start_x = (target_w - bw) // 2
    start_y = (target_h - bh) // 2
    bytes_per_row = (bw + 7) // 8

    # Vectorised bit unpack.  For each output pixel (yy, xx) compute
    # source bitmap coords (sy, sx), reject out-of-bounds, then look
    # up the bit.
    yy, xx = np.mgrid[0:target_h, 0:target_w]
    sx = xx - start_x
    sy = yy - start_y
    in_bounds = (sx >= 0) & (sx < bw) & (sy >= 0) & (sy < bh)
    if not in_bounds.any():
        return frame.tobytes()
    valid_sx = sx[in_bounds]
    valid_sy = sy[in_bounds]
    byte_idx = valid_sy * bytes_per_row + (valid_sx // 8)
    bit_idx = 7 - (valid_sx % 8)
    valid_byte_mask = byte_idx < data.size
    byte_idx = byte_idx[valid_byte_mask]
    bit_idx = bit_idx[valid_byte_mask]
    pixel_values = (data[byte_idx] >> bit_idx) & 1
    on_mask = np.zeros_like(in_bounds, dtype=bool)
    temp = np.zeros_like(in_bounds, dtype=bool)
    temp[in_bounds] = valid_byte_mask
    on_mask[temp] = pixel_values == 1
    frame[on_mask, 0] = fg_rgb[0]
    frame[on_mask, 1] = fg_rgb[1]
    frame[on_mask, 2] = fg_rgb[2]
    frame[on_mask, 3] = 255
    return frame.tobytes()
