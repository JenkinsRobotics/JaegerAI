"""Animation node — Mochi-vendored adapters + skill-tree integration.

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

0.8 M2c: "the module IS the engine" (kokoro_tts M1 / whisper_stt M2b
precedent) — this package's own ``module.yaml`` (slot ``animation``)
declares its topics/tools/factory/``requires_libraries``, and its
settings-catalog config slice (``config.py``'s ``AvatarConfig``, moved
here verbatim from ``core/instance/schemas.py``) is nested at
``Config.avatar`` via a guarded import in ``schemas.py``.
"""

from typing import Any

from jaeger_os.contract.ports import ANIMATION_BRIDGE_DEFAULT_PORT

from .auto_state import AvatarAutoStateDriver
from .base import AnimationAdapter, FrameBuffer
from .config import AvatarConfig
from .node import AnimationNode

__all__ = [
    "AnimationAdapter",
    "AnimationNode",
    "AvatarAutoStateDriver",
    "AvatarConfig",
    "FrameBuffer",
    "make_animation_node",
]


def make_animation_node(bus: Any, config: dict[str, Any]) -> AnimationNode:
    """Chassis-contract factory ``(bus, config) -> AnimationNode``.

    0.8 U3b: constructs the node DIRECTLY on the chassis-injected
    ``bus`` via ``runtime._build_animation_node`` rather than calling
    ``ensure_animation_node()`` — same recursion hazard as
    ``make_tts_node``: the supervisor's ``ThreadHandle.start()`` calls
    this factory, and ``ensure_animation_node()``'s supervisor branch
    would call right back into ``supervisor.start("animation")``.
    """
    from jaeger_os.nodes.runtime import _build_animation_node
    return _build_animation_node(
        bus,
        bridge_host=str(config.get("bridge_host", "127.0.0.1")),
        bridge_port=int(config.get("bridge_port", ANIMATION_BRIDGE_DEFAULT_PORT)),
        enable_bridge=bool(config.get("enable_bridge", True)),
    )
