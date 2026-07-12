"""AnimationAdapter Protocol — the contract every animation adapter implements.

The frame format (:class:`FrameBuffer`) is owned by the MEDIA node
(``jaeger_os.nodes.media.frames``) — the asset->frame foundation this node builds
on. We re-export it here for animation's own adapters and add the
animation-specific Protocol (skill_id / level for the skill tree).
"""

from __future__ import annotations

from typing import Protocol

from jaeger_ai.nodes.media.frames import FrameBuffer

__all__ = ["AnimationAdapter", "FrameBuffer"]


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
