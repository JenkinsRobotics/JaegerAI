"""MathAdapter — L4 procedural animation level.

Dynamically loads a Python file that defines a :class:`MathScript`
subclass; delegates rendering to it.  This is how Mochi-style faces
(eyes blinking, mouth shapes) get authored — operator writes a small
class that draws into an RGB numpy buffer, the adapter wraps it for
the JROS Protocol + RGBA8 output.

Architecture vendored from Mochi
─────────────────────────────────
Distilled from Mochi's MathHandler.  Same importlib-based plug-in
discovery; same delegation pattern.  Two changes for JROS:

  1. Scripts subclass JROS's :class:`MathScript` (a Protocol-ish
     base) instead of Mochi's Animation(ABC) — keeps the contract
     minimal.
  2. Scripts draw RGB (3 channels); the adapter converts to RGBA8
     before emitting the FrameBuffer.

Apache 2.0; see ``dev/docs/library_review/mochi_demo.md``.

Skill tree
──────────
``skill_id = "animation.math"``, ``level = 4``.  Procedural is the
gateway to L5/L6 — once an operator's writing math scripts they're
ready for rigged + generative.

Security note
─────────────
This adapter executes arbitrary Python.  Production use should
restrict ``asset_path`` to a sandbox (e.g.,
``<instance>/avatar/scripts/``).  0.5.x followup wires this through
``jaeger_os.agent.tools._common._resolve_under``; the standalone
adapter trusts its caller for now.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Callable

import numpy as np

from ..base import FrameBuffer


class MathScript:
    """Base contract for operator-authored procedural animations.

    Subclasses MUST implement :meth:`render_into`; everything else
    has sensible defaults.

      def render_into(self, t: float, frame_rgb) -> None:
          # frame_rgb is a NumPy array of shape (h, w, 3), uint8.
          # Mutate it in place.

    Optional hooks:
      :meth:`on_enter` runs once when the clip starts (params live here)
      :meth:`on_event` runs when a Timeline clip carries an event tag
    """

    # Default runtime params — present on every MathScript so the
    # AnimationNode's set_runtime_param can update them without
    # the script having to opt in.  Subclasses can override
    # initial values in on_enter.
    amplitude_param: float = 0.0

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def on_enter(self, **kwargs: Any) -> None:
        """Optional setup hook — runs once when the clip starts.
        Override to read params + initialise per-clip state."""

    def on_event(self, event: str, **kwargs: Any) -> None:
        """Optional event hook — Timeline clips can carry named events
        (e.g. "blink_now") that the script reacts to.  Default
        ignores."""

    def render_into(self, t: float, frame_rgb: np.ndarray) -> None:
        """REQUIRED: draw the frame at time ``t`` (seconds since the
        clip started) into ``frame_rgb`` (shape (h, w, 3), uint8).
        Must mutate the array in place."""
        raise NotImplementedError


class MathAdapter:
    """Run an operator-authored procedural animation."""

    skill_id: str = "animation.math"
    level: int = 4

    def __init__(self) -> None:
        self._script: MathScript | None = None
        self._width: int = 0
        self._height: int = 0
        self._start_t: float | None = None
        self._fps: float = 30.0
        self._duration_ms_per_frame: int = int(round(1000.0 / 30.0))

    # ── Protocol surface ──────────────────────────────────────────

    def open(self, asset_path: str, *, width: int, height: int,
             params: dict) -> None:
        """Load the Python file, instantiate the MathScript subclass.

        ``params``:
          ``fps``           target frame rate (default 30)
          everything else   passed verbatim to ``script.on_enter()``
        """
        p = dict(params or {})
        self._fps = float(p.pop("fps", 30.0))
        self._duration_ms_per_frame = max(
            1, int(round(1000.0 / max(0.1, self._fps))),
        )
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        cls = _load_math_script_class(asset_path)
        if cls is None:
            raise ValueError(
                f"no MathScript subclass found in {asset_path!r}"
            )
        self._script = cls(self._width, self._height)
        try:
            self._script.on_enter(**p)
        except Exception:
            # If on_enter raises, drop the script so next_frame
            # returns None — the node logs it via its normal error
            # path.
            self._script = None
            raise
        self._start_t = None

    def set_runtime_param(self, key: str, value: Any) -> None:
        """Push a real-time parameter update to the running
        MathScript.  Lip-sync uses this to feed amplitude from
        :class:`jaeger_os.transport.topics.TtsChunk` events into the script
        between frames.

        The script reads the value at its next ``render_into``
        call.  No-op if the script isn't open.
        """
        if self._script is None:
            return
        # Map well-known runtime params to the conventional
        # attribute names MathScripts use.
        if key == "amplitude":
            setattr(self._script, "amplitude_param", float(value))
        else:
            setattr(self._script, f"{key}_param", value)

    def close(self) -> None:
        self._script = None
        self._start_t = None

    def next_frame(self, t: float) -> FrameBuffer | None:
        if self._script is None:
            return None
        if self._start_t is None:
            self._start_t = t
        elapsed = max(0.0, t - self._start_t)
        # Draw RGB; convert to RGBA before emitting.
        rgb = np.zeros(
            (self._height, self._width, 3), dtype=np.uint8,
        )
        try:
            self._script.render_into(elapsed, rgb)
        except Exception:
            return None
        rgba = np.empty(
            (self._height, self._width, 4), dtype=np.uint8,
        )
        rgba[..., :3] = rgb
        rgba[..., 3] = 255
        return FrameBuffer(
            width=self._width,
            height=self._height,
            data=rgba.tobytes(),
            duration_ms=self._duration_ms_per_frame,
            is_final=False,
        )


# ── helpers ───────────────────────────────────────────────────────

def _load_math_script_class(asset_path: str) -> type[MathScript] | None:
    """Import the file at ``asset_path``; return the first
    :class:`MathScript` subclass it defines (excluding the base)."""
    module_name = os.path.splitext(os.path.basename(asset_path))[0]
    spec = importlib.util.spec_from_file_location(module_name, asset_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, MathScript)
            and attr is not MathScript
        ):
            return attr
    return None
