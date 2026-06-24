"""ImageAdapter — L1 STATIC animation level.

Displays a single raster image (PNG/JPG/BMP/WebP — anything Pillow
opens).  Holds the same frame for the entire clip duration; returns
``None`` once the operator-specified duration elapses (or stays
forever if ``duration_ms=0`` is configured upstream — the node
handles the natural-end semantics).

Architecture vendored from Mochi
─────────────────────────────────
Distilled from Mochi's ``image_handler.py`` + ``decoders/image_decoder.py``
+ ``media_base.py`` (Apache 2.0; see
``dev/docs/library_review/mochi_demo.md`` for the audit).  Simplified
to the JROS :class:`AnimationAdapter` Protocol — open / close /
next_frame — and converted to RGBA8 output so the Swift renderer
sees a uniform pixel layout.

Skill tree
──────────
``skill_id = "animation.image"``, ``level = 1``.  Each successful
play awards XP via the AnimationNode; sustained use eventually
masters the skill, unlocking L2 sprite adapters.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from ..frames import FrameBuffer


class ImageAdapter:
    """Render a single static image as one held frame."""

    skill_id: str = "animation.image"
    level: int = 1

    def __init__(self) -> None:
        self._buffer: bytes = b""
        self._width: int = 0
        self._height: int = 0
        self._emitted: bool = False
        self._asset_path: str = ""
        self._params: dict = {}

    # ── Protocol surface ──────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Load + resize the image into an RGBA8 byte buffer.

        ``params`` honoured:
          ``fit``           "contain" (default), "cover", "fill", "letterbox"
          ``letterbox_rgb`` (r, g, b) for letterbox bands; default black
        """
        self._params = dict(params or {})
        self._asset_path = asset_path
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        self._emitted = False
        fit = str(self._params.get("fit", "contain")).lower()
        letterbox_rgb = tuple(self._params.get("letterbox_rgb", (0, 0, 0)))
        self._buffer = _load_to_rgba8(
            asset_path,
            target=(self._width, self._height),
            fit=fit,
            letterbox_rgb=letterbox_rgb,
        )

    def close(self) -> None:
        self._buffer = b""
        self._asset_path = ""
        self._emitted = False

    def next_frame(self, t: float) -> FrameBuffer | None:
        """Return the held frame once; subsequent calls return None
        so the AnimationNode's stream loop drops back to the
        operator-specified ``duration_ms`` cap.

        A non-zero ``duration_ms`` on the AnimationCommand keeps
        the same image visible for that long; without it, this
        adapter emits one frame and ends — typically the brain
        publishes a follow-up command (a different image or an
        idle clip) to fill the next slot.
        """
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

def _load_to_rgba8(
    asset_path: str,
    *,
    target: tuple[int, int],
    fit: str,
    letterbox_rgb: tuple[int, int, int],
) -> bytes:
    """Open ``asset_path`` via Pillow, fit to ``target`` size, return
    RGBA8 bytes (``len == target.w * target.h * 4``).

    Fit modes:
      ``contain``    — preserve aspect, fit inside target, letterbox edges
      ``cover``      — preserve aspect, fill target, crop overflow
      ``fill``       — stretch to exact target (ignores aspect)
      ``letterbox``  — alias for ``contain``
    """
    with Image.open(asset_path) as src:
        rgba = src.convert("RGBA")
        target_w, target_h = target
        if fit in ("contain", "letterbox"):
            out = _fit_contain(rgba, target_w, target_h, letterbox_rgb)
        elif fit == "cover":
            out = _fit_cover(rgba, target_w, target_h)
        elif fit == "fill":
            out = rgba.resize((target_w, target_h), Image.LANCZOS)
        else:
            # Unknown fit mode — default to contain (safe).
            out = _fit_contain(rgba, target_w, target_h, letterbox_rgb)
        return out.tobytes()


def _fit_contain(
    img: Image.Image,
    target_w: int, target_h: int,
    bg_rgb: tuple[int, int, int],
) -> Image.Image:
    """Aspect-preserving fit inside target; pad edges with bg_rgb."""
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new(
        "RGBA",
        (target_w, target_h),
        (bg_rgb[0], bg_rgb[1], bg_rgb[2], 255),
    )
    paste_x = (target_w - new_w) // 2
    paste_y = (target_h - new_h) // 2
    canvas.paste(resized, (paste_x, paste_y), resized)
    return canvas


def _fit_cover(
    img: Image.Image, target_w: int, target_h: int,
) -> Image.Image:
    """Aspect-preserving fill; crop overflow."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(1, int(round(src_w * scale)))
    new_h = max(1, int(round(src_h * scale)))
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    crop_x = (new_w - target_w) // 2
    crop_y = (new_h - target_h) // 2
    return resized.crop((
        crop_x, crop_y,
        crop_x + target_w, crop_y + target_h,
    ))
