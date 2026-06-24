"""Avatar player — the floating avatar window (mirrors the media player popup).

The animation node (which IS the avatar node) streams rendered avatar frames on
``/sense/avatar_frame``; this popup displays them — the same node+popup pattern
as media. 2D today; 3D is a future animation level inside the animation node.
"""

from jaeger_os.interfaces.avatar_player.window import (
    AvatarView, FloatingAvatarPlayer, make_surface,
)

__all__ = ["AvatarView", "FloatingAvatarPlayer", "make_surface"]
