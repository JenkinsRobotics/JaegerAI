"""Default emotion -> adapter/asset mapping — shared by the
``set_avatar_state`` agent tool and the animation node's own
:class:`AvatarAutoStateDriver`.

Moved out of ``agent/tools/avatar.py`` in the 0.9 CI-dependency-rule
pass (dev/docs/vision/THREE_TIER_STRUCTURE.md, law 2): this is static
node-level data (an emotion name -> AnimationCommand shape), not tool
logic, and ``nodes/animation/auto_state.py`` (runtime tier) needs the
exact same table to publish AnimationCommands that match what an
explicit ``set_avatar_state`` call would produce — without importing
``agent/`` (the nervous-system rule).

Operators can still override per-instance by dropping a JSON file at
``<instance>/avatar/expressions.json`` with the same shape — that
override lookup stays in ``agent/tools/avatar.py`` (it needs the
active instance's layout, which is a tool-call-time concern); this
module only carries the built-in fallback table + the framework's
bundled default asset directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_EXPRESSIONS: dict[str, dict[str, Any]] = {
    "neutral":   {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "neutral"}},
    "happy":     {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "happy"}},
    "sad":       {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "sad"}},
    "focused":   {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "focused"}},
    "thinking":  {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "thinking"}},
    "speaking":  {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "speaking"}},
    "listening": {"adapter": "math", "asset": "faces/lilith_face.py",
                   "params": {"emotion": "listening"}},
}


# Framework default face scripts ship under agent/personas/lilith/avatar
# (the character-asset bundle location, unchanged by this move — only
# the constant that points at it moved). A fresh instance gets a
# working face out of the box without the wizard having to copy files.
FRAMEWORK_AVATAR_DEFAULTS = (
    Path(__file__).resolve().parents[2]  # jaeger_os/
    / "agent" / "personas" / "lilith" / "avatar"
)


__all__ = ["DEFAULT_EXPRESSIONS", "FRAMEWORK_AVATAR_DEFAULTS"]
