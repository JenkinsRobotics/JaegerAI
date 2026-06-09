"""Vision engine — the last-resort screenshot fallback.

The bottom rung of the capability ladder. Triggered when:

  * the target app has no AppleScript dictionary, AND
  * the target is not a web page, AND
  * the target element isn't visible in the AX tree

Most common real-world cases: canvas / WebGL apps, games, image
viewers, design tools (Figma, Photoshop) whose UI sits inside a
single big AX object, or any app that just doesn't ship AX support.

Delegates to the universal :mod:`jaeger_os.agent.skills.computer_use`
skill's primitives (screenshot, click_xy, type_text). That keeps
the screenshot loop in ONE place — improvements to it (better
OCR, vision-LM grounding, etc.) benefit both this engine and any
non-Mac host using the universal skill directly.
"""

from __future__ import annotations

import time
from typing import Any

from jaeger_os.agent.skills.macos_computer_v1.engines import Action, Engine, EngineResult


_NAME = "vision"
_PRIORITY = 90  # always last


# Action kinds the vision engine claims as a fallback. These are
# the "you have an (x, y) point" actions — anything semantic
# (press by label, set field by name) is upstream.
_VISION_KINDS = frozenset({
    "click_xy", "click_point",
    "type_text", "type_raw",
    "press_key",
    "screenshot",
    "read_screen",
})


class VisionEngine:
    """Screenshot-loop fallback. Delegates to the universal
    ``computer_use`` skill's tool surface so the heavy lifting
    (screen capture, OCR, vision-LM grounding when wired) lives
    in one place."""

    name: str = _NAME
    priority: int = _PRIORITY

    def is_available(self) -> tuple[bool, str]:
        """Vision is universally available as long as the universal
        skill's screenshot primitive is loadable. That's the
        ``computer_screenshot`` tool, which needs ``screencapture``
        on macOS — present by default."""
        import shutil
        if shutil.which("screencapture") is None:
            return False, "screencapture not on PATH (non-macOS hosts need a port)"
        return True, "ready"

    def can_handle(self, action: Action) -> float:
        """Vision is the last-tier fallback. It claims explicit
        ``_xy`` / ``click_point`` actions at high confidence, and
        offers a low non-zero confidence on generic kinds so the
        planner picks it ONLY when no higher tier said yes."""
        kind = (action.kind or "").lower()
        if kind in _VISION_KINDS:
            return 0.95
        # Generic fallback bid: planner uses it as the last resort.
        if kind in ("click", "type", "read", "press"):
            return 0.15
        return 0.0

    def execute(self, action: Action) -> EngineResult:
        started = time.perf_counter()
        kind = (action.kind or "").lower()
        args = action.args or {}
        # Lazy import the universal-skill primitives — they only get
        # loaded if vision actually fires (most runs won't need them
        # on macOS once applescript + ax cover the common cases).
        try:
            from jaeger_os.agent.skills.computer_use_v1 import computer_use as _v1
        except Exception as exc:  # noqa: BLE001
            return EngineResult(
                ok=False, engine=_NAME,
                error=f"universal computer_use unavailable: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        try:
            if kind in ("click_xy", "click_point", "click"):
                result = _v1.computer_click(
                    x=int(args.get("x", 0)), y=int(args.get("y", 0)),
                )
            elif kind in ("type_text", "type_raw", "type"):
                result = _v1.computer_type_text(
                    text=str(args.get("text", args.get("value", ""))),
                )
            elif kind == "press_key":
                result = _v1.computer_press_key(key=str(args.get("key", "")))
            elif kind == "screenshot":
                result = _v1.computer_screenshot(
                    path=str(args.get("path", "")),
                )
            elif kind in ("read_screen", "read"):
                result = _v1.computer_read_screen()
            else:
                return EngineResult(
                    ok=False, engine=_NAME,
                    error=f"vision_engine does not handle kind={kind!r}",
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                )
        except Exception as exc:  # noqa: BLE001
            return EngineResult(
                ok=False, engine=_NAME,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        elapsed = (time.perf_counter() - started) * 1000.0
        ok = bool(result.get("ok", True)) if isinstance(result, dict) else False
        return EngineResult(
            ok=ok, engine=_NAME, result=result,
            error="" if ok else str(result.get("error", "")
                                    if isinstance(result, dict) else ""),
            elapsed_ms=elapsed,
        )


__all__ = ["VisionEngine"]
