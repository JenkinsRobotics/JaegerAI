"""FrameBuffer — the canonical RGBA frame format, owned by the media node.

Media is the asset->frame foundation other nodes build on: anything that turns
an asset into frames (the media node's decoders, the animation node's adapters)
produces these, so the bus + every renderer see one consistent shape.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FrameBuffer:
    """One rendered frame. ``data`` is raw RGBA8 bytes (4 bytes/pixel,
    row-major): width * height * 4 == len(data)."""

    width: int
    height: int
    data: bytes  # RGBA8, w*h*4 bytes
    duration_ms: int = 0  # how long this frame stays visible
    is_final: bool = False  # last frame of a one-shot clip
