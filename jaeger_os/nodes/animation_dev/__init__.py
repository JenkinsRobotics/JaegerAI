"""Animation node — Mochi-vendored adapters + skill-tree integration.

LIVE, not staging — despite the ``_dev`` suffix. Its ``mscript/`` scenes +
``mscript.logging_utils`` are imported by ``interfaces/studio/pages.py`` and
``interfaces/v4/mochi_gui.py``, so this stays under ``nodes/`` (moving it to
``dev/staging/`` would break both GUIs). Distinct from the generic
``nodes/animation/`` node; this is the Mochi MScript renderer path.

The node owns one active :class:`AnimationAdapter` at a time; it
subscribes to ``/act/animation`` + ``/act/animation_stop`` on the
bus and renders pixel buffers it ships to the Swift renderer (or
any other consumer) via WebSocket.

Each adapter implementation is a SKILL TREE NODE (see
``dev/docs/skills/SKILL_TREE.md``).  When a clip plays, the corresponding
skill earns XP — operators see their agent's animation capability
grow with use.

Adapter levels (operator-locked 2026-06-08):

  L1  static       ImageAdapter, BitmapAdapter
  L2  sprite       SpriteAdapter
  L3  gif          GifAdapter
  L4  video        VideoAdapter, MathAdapter (procedural)
  L5  rigged       (deferred — Live2D / Spine)
  L6  generative   (deferred — Wan2.1 / SVD / NeRF)

See ``dev/docs/library_review/mochi_demo.md`` for the vendoring
audit + per-adapter origin.
"""

from typing import Any

from .auto_state import AvatarAutoStateDriver
from .base import AnimationAdapter, FrameBuffer
from .node import AnimationNode

__all__ = [
    "AnimationAdapter",
    "AnimationNode",
    "AvatarAutoStateDriver",
    "FrameBuffer",
    "make_animation_node",
]


def make_animation_node(bus: Any, config: dict[str, Any]) -> AnimationNode:
    """Chassis-contract factory ``(bus, config) -> AnimationNode``.

    J5A — points jaeger_os.toml's [[node]] animation entry at a callable
    matching the format 0.1 chassis contract. Delegates to
    ``jaeger_os.nodes.runtime.ensure_animation_node`` which owns the
    idempotent singleton lifecycle (and the FrameBridge WebSocket
    sidecar). The chassis ``bus`` argument is accepted but not
    propagated — JROS's runtime uses the legacy global bus until
    J5B unifies the two.
    """
    from jaeger_os.nodes.runtime import ensure_animation_node
    return ensure_animation_node(
        bridge_host=str(config.get("bridge_host", "127.0.0.1")),
        bridge_port=int(config.get("bridge_port", 8765)),
        enable_bridge=bool(config.get("enable_bridge", True)),
    )
