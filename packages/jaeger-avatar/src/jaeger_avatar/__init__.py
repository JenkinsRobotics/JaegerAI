"""jaeger-avatar: 2D/3D VR Avatar backend (VRM 0.x/1.0, GLB, Rive, 2D) + Kokoro viseme timelines."""

from .living_link import (
    DEFAULT_AVATAR_PORT,
    DEFAULT_FACE,
    AvatarLink,
    avatar_app_serving,
    launch_avatar_app,
)
from .store import (
    BUDGETS,
    EMOTIONS,
    FORMATS,
    SCHEMA,
    AvatarError,
    AvatarStore,
    budget_report,
    build_viseme_timeline,
    inspect_avatar_bytes,
    inspect_glb_bytes,
)

__all__ = [
    "AvatarError",
    "AvatarLink",
    "AvatarStore",
    "BUDGETS",
    "DEFAULT_AVATAR_PORT",
    "DEFAULT_FACE",
    "EMOTIONS",
    "FORMATS",
    "SCHEMA",
    "avatar_app_serving",
    "budget_report",
    "build_viseme_timeline",
    "inspect_avatar_bytes",
    "inspect_glb_bytes",
    "launch_avatar_app",
]
