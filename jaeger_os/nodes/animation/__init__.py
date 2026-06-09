"""Animation node — Mochi-vendored adapters + skill-tree integration.

The node owns one active :class:`AnimationAdapter` at a time; it
subscribes to ``/act/animation`` + ``/act/animation_stop`` on the
bus and renders pixel buffers it ships to the Swift renderer (or
any other consumer) via WebSocket.

Each adapter implementation is a SKILL TREE NODE (see
``dev_docs/SKILL_TREE.md``).  When a clip plays, the corresponding
skill earns XP — operators see their agent's animation capability
grow with use.

Adapter levels (operator-locked 2026-06-08):

  L1  static       ImageAdapter, BitmapAdapter
  L2  sprite       SpriteAdapter
  L3  gif          GifAdapter
  L4  video        VideoAdapter, MathAdapter (procedural)
  L5  rigged       (deferred — Live2D / Spine)
  L6  generative   (deferred — Wan2.1 / SVD / NeRF)

See ``dev_docs/library_review/mochi_demo.md`` for the vendoring
audit + per-adapter origin.
"""

from .auto_state import AvatarAutoStateDriver
from .base import AnimationAdapter, FrameBuffer
from .node import AnimationNode

__all__ = [
    "AnimationAdapter",
    "AnimationNode",
    "AvatarAutoStateDriver",
    "FrameBuffer",
]
