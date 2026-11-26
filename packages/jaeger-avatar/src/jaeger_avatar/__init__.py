"""jaeger-avatar: 2D/3D VR Avatar backend (VRM 0.x/1.0, GLB, Rive, 2D) + Kokoro viseme timelines."""

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
    "AvatarStore",
    "BUDGETS",
    "EMOTIONS",
    "FORMATS",
    "SCHEMA",
    "budget_report",
    "build_viseme_timeline",
    "inspect_avatar_bytes",
    "inspect_glb_bytes",
]
