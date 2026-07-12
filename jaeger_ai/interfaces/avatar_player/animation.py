"""Avatar-animation plugin seam.

The avatar surfaces don't hardcode a widget — they ask here for the *active*
avatar animation. Today the only plugin is the VoiceOrb (agent face + reactive
voice spectrum). Future plugins — lip-sync, facial animation, a live 3D avatar —
register a factory to replace it, and no window changes.

Contract: a plugin is ``make(ctx) -> QWidget``. The widget self-wires to the bus
from ``ctx`` (agent state + audio) and renders the agent's avatar. Register the
active one with :func:`register`; :func:`make_avatar` builds it (defaulting to
the VoiceOrb when nothing else is registered).
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtWidgets import QWidget

AvatarFactory = Callable[[Any], QWidget]

_active: AvatarFactory | None = None


def register(factory: AvatarFactory | None) -> None:
    """Install the active avatar-animation plugin (None → back to the default)."""
    global _active
    _active = factory


def make_avatar(ctx: Any = None) -> QWidget:
    """Build the active avatar-animation widget for a surface."""
    if _active is not None:
        return _active(ctx)
    from jaeger_ai.interfaces.avatar_player.voice_orb import VoiceOrb
    return VoiceOrb(ctx)
