"""Animation adapters — one per animation level + sub-type.

Each adapter is a SkillNode in the operator's skill tree.  See
``dev/docs/SKILL_TREE.md`` + ``dev/docs/library_review/mochi_demo.md``
for the levels + vendoring map.

Levels in this package:

  L1 — STATIC      ImageAdapter, BitmapAdapter
  L2 — SPRITE      SpriteAdapter
  L3 — GIF         GifAdapter
  L4 — VIDEO+PROC  VideoAdapter, MathAdapter
  L5 — RIGGED      (deferred — adapter slot reserved)
  L6 — GENERATIVE  (deferred — adapter slot reserved)
"""

from .bitmap_adapter import BitmapAdapter
from .gif_adapter import GifAdapter
from .image_adapter import ImageAdapter
from .math_adapter import MathAdapter, MathScript
from .sprite_adapter import SpriteAdapter

__all__ = [
    "BitmapAdapter",
    "GifAdapter",
    "ImageAdapter",
    "MathAdapter",
    "MathScript",
    "SpriteAdapter",
]
