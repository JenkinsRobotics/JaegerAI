"""AnimationAdapter Protocol — the contract every adapter implements.

Vendored shape from Mochi's ``Animation(ABC)`` (Apache 2.0; see
``dev/docs/library_review/mochi_demo.md``).  Adapted to JROS conventions:

  * Protocol instead of ABC for duck-typed adapter swaps
  * msgspec-friendly state model
  * Skill-tree integration — each adapter declares its ``skill_id``
    so the AnimationNode can route XP events on play / completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class FrameBuffer:
    """One rendered animation frame.

    The AnimationNode ships these to the Swift renderer over the
    WebSocket bridge.  ``data`` is raw RGBA bytes (4 bytes/pixel,
    row-major) — width × height × 4 = len(data).  Adapters that
    render in other formats convert here so the renderer sees one
    consistent shape.
    """

    width: int
    height: int
    data: bytes  # RGBA8, w*h*4 bytes
    duration_ms: int = 0  # how long this frame stays visible
    is_final: bool = False  # last frame of the clip (one-shot end)


class AnimationAdapter(Protocol):
    """Render an animation asset frame-by-frame.

    ``skill_id`` — the skill-tree node this adapter advances.  When
    the node successfully plays a clip via this adapter, the
    AnimationNode awards XP to that skill.

    ``level`` — the skill-tree LEVEL this adapter implements
    (L1 = static, L2 = sprite, L3 = gif, L4 = video/procedural,
    ...).  Lets the operator see at a glance which adapter
    level is in use.
    """

    skill_id: str
    level: int

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Prepare the adapter to render the given asset.  Idempotent
        on the same asset; switching assets re-opens.  ``params`` is
        adapter-specific (e.g., ``{"loop": True, "fit": "contain"}``)."""
        ...

    def close(self) -> None:
        """Release any decoded resources.  Idempotent."""
        ...

    def next_frame(self, t: float) -> FrameBuffer | None:
        """Render the frame appropriate for time ``t`` (seconds
        since the clip started).  Returns ``None`` when the clip is
        complete (only one-shot adapters; looping ones never return
        None until ``close()`` is called)."""
        ...
