"""Browser engine — CDP / Playwright for live web pages.

When the action targets a web page (open URL, click DOM element by
selector, fill form field, extract text), this engine talks to the
browser directly rather than driving the OS chrome around it. ~5-10×
faster than screenshot-clicking a button on a page; also more
reliable (DOM is stable, screen coordinates are not).

Today this is a thin wrapper that delegates to the existing
``browser()`` tool implementation in
:mod:`jaeger_os.core.tools.browser`. The point is to let the
planner CHOOSE the browser path semantically — "fill a form" or
"click selector" routes here instead of the AX / vision tiers,
regardless of whether the browser window has focus.

A future pass can push the integration deeper (per-tab CDP
sessions, headless mode for tests, etc.) — for now this is a
priority-20 router into the surface that already works.
"""

from __future__ import annotations

import time
from typing import Any

from jaeger_os.agent.skills.macos_computer_v1.engines import Action, Engine, EngineResult


_NAME = "browser"
_PRIORITY = 20


# Action kinds the browser engine claims when the target is a URL
# or selector. ``open_url`` / ``goto`` are the common entry points;
# the rest mirror the existing ``browser()`` tool's verbs.
_BROWSER_KINDS = frozenset({
    "open_url", "goto", "browser_open",
    "click_selector", "browser_click",
    "fill", "browser_type",
    "extract_text", "browser_read",
    "screenshot_page", "browser_snapshot",
})


class BrowserEngine:
    """Routes browser actions to the existing Playwright surface.
    Lives in the ladder so the planner can pick it WITHOUT having
    to encode "is this a URL?" in every other engine's
    ``can_handle``."""

    name: str = _NAME
    priority: int = _PRIORITY

    def is_available(self) -> tuple[bool, str]:
        """Playwright is a JROS base dep; available iff the chromium
        runtime is installed (``playwright install chromium``)."""
        try:
            import playwright  # noqa: F401
        except ImportError as exc:
            return False, f"playwright not importable: {exc}"
        return True, "ready"

    def can_handle(self, action: Action) -> float:
        kind = (action.kind or "").lower()
        if kind in _BROWSER_KINDS:
            return 0.95
        # A URL-shaped target is a strong hint even on a generic kind.
        target = (action.target or action.args.get("url") or "").lower()
        if target.startswith(("http://", "https://")):
            if kind in ("open", "click", "type", "read"):
                return 0.7
        return 0.0

    def execute(self, action: Action) -> EngineResult:
        started = time.perf_counter()
        try:
            from jaeger_os.core.tools.browser import browser as browser_tool
        except Exception as exc:  # noqa: BLE001
            return EngineResult(
                ok=False, engine=_NAME,
                error=f"browser tool unavailable: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        kind = (action.kind or "").lower()
        args = action.args or {}
        # Map the engine action kinds onto the existing
        # ``browser(action=...)`` verb surface.
        verb_map = {
            "open_url": "open", "goto": "open", "browser_open": "open",
            "click_selector": "click", "browser_click": "click",
            "fill": "type", "browser_type": "type",
            "extract_text": "snapshot", "browser_read": "snapshot",
            "screenshot_page": "snapshot", "browser_snapshot": "snapshot",
        }
        verb = verb_map.get(kind, kind)
        try:
            result = browser_tool(
                action=verb,
                url=action.target or args.get("url", ""),
                element=int(args.get("element", 0) or 0),
                text=str(args.get("text", "") or args.get("value", "")),
                direction=str(args.get("direction", "down")),
                key=str(args.get("key", "Enter")),
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


__all__ = ["BrowserEngine"]
