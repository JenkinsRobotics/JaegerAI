"""Animation adapters — one per animation level + sub-type.

Each adapter is a SkillNode in the operator's skill tree.  See
``dev_docs/SKILL_TREE.md`` + ``dev_docs/library_review/mochi_demo.md``
for the levels + vendoring map.

Levels in this package:

  L1 — STATIC      ImageAdapter, BitmapAdapter
  L2 — SPRITE      SpriteAdapter
  L3 — GIF         GifAdapter
  L4 — VIDEO+PROC  VideoAdapter, MathAdapter
  L5 — RIGGED      (deferred — adapter slot reserved)
  L6 — GENERATIVE  (deferred — adapter slot reserved)
"""

from .image_adapter import ImageAdapter

__all__ = [
    "ImageAdapter",
]
