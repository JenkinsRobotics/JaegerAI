"""AppleScript engine — the fastest tier of the ladder.

When the target app has an AppleScript dictionary, this engine
runs the action with ONE ``osascript`` round-trip — no pointer
movement, no focus steal, returns structured data the planner
can use without another query. Roughly 10-30× faster than the
AX + screenshot path for the apps it covers.

The dispatch table maps ``(app, action_kind)`` to a small
AppleScript template. Adding an app is: one entry per supported
action. Adding an action is: one new template per app that has
the corresponding command.

Apps shipped today:
  * Calculator — open / press / read result
  * Notes — create note, append, list
  * Safari — open URL, run JS, current URL/title
  * Mail — count unread, new draft
  * Finder — open path, reveal item
  * Music — play / pause / next / volume

Anything not in the dispatch table abstains (``can_handle = 0``)
and the planner falls through to the next tier.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

from jaeger_ai.agent.skills.macos_computer_v1.engines import Action, Engine, EngineResult


_NAME = "applescript"
_PRIORITY = 10  # top of the ladder when applicable


# Dispatch table: (app_lower, action_kind) → AppleScript template.
# ``{value}`` is filled from action.args at call time. Templates
# are kept tight — each one round-trips a single OSAscript invoke.
# Returning ``stdout`` makes ``read`` actions composable: the
# planner can pass the result into the next step.
_DISPATCH: dict[tuple[str, str], str] = {
    # ── Calculator ────────────────────────────────────────────────
    ("calculator", "open"): (
        'tell application "Calculator" to activate'
    ),
    ("calculator", "press"): (
        # ``value`` is the button label (digits, operators, "=").
        'tell application "System Events" to tell process "Calculator" '
        'to click button "{value}" of group 1 of window 1'
    ),
    ("calculator", "read_result"): (
        'tell application "System Events" to tell process "Calculator" '
        'to return value of static text 1 of group 1 of window 1'
    ),
    # ── Notes ─────────────────────────────────────────────────────
    ("notes", "new_note"): (
        'tell application "Notes" to make new note with properties '
        '{{body:"{value}"}}'
    ),
    ("notes", "list_notes"): (
        'tell application "Notes" to return name of every note'
    ),
    # ── Safari ────────────────────────────────────────────────────
    ("safari", "open_url"): (
        'tell application "Safari" to open location "{value}"'
    ),
    ("safari", "current_url"): (
        'tell application "Safari" to return URL of current tab of window 1'
    ),
    ("safari", "current_title"): (
        'tell application "Safari" to return name of current tab of window 1'
    ),
    ("safari", "run_js"): (
        'tell application "Safari" to do JavaScript "{value}" '
        'in current tab of window 1'
    ),
    # ── Mail ──────────────────────────────────────────────────────
    ("mail", "unread_count"): (
        'tell application "Mail" to return unread count of inbox'
    ),
    # ── Finder ────────────────────────────────────────────────────
    ("finder", "open_path"): (
        'tell application "Finder" to open POSIX file "{value}"'
    ),
    ("finder", "reveal_path"): (
        'tell application "Finder" to reveal POSIX file "{value}"'
    ),
    # ── Music ─────────────────────────────────────────────────────
    ("music", "play"):  'tell application "Music" to play',
    ("music", "pause"): 'tell application "Music" to pause',
    ("music", "next"):  'tell application "Music" to next track',
    ("music", "previous"): 'tell application "Music" to previous track',
    ("music", "current_track"): (
        'tell application "Music" to return name of current track & " — " & '
        'artist of current track'
    ),
    # ── Chrome (same shape as Safari; both are common browsers) ───
    ("google chrome", "open_url"): (
        'tell application "Google Chrome" to open location "{value}"'
    ),
    ("google chrome", "current_url"): (
        'tell application "Google Chrome" to return URL of active tab '
        'of front window'
    ),
    ("google chrome", "current_title"): (
        'tell application "Google Chrome" to return title of active tab '
        'of front window'
    ),
    ("google chrome", "run_js"): (
        'tell application "Google Chrome" to execute active tab of front '
        'window javascript "{value}"'
    ),
    # ── Reminders ─────────────────────────────────────────────────
    ("reminders", "new_reminder"): (
        'tell application "Reminders" to make new reminder with properties '
        '{{name:"{value}"}}'
    ),
    ("reminders", "list_lists"): (
        'tell application "Reminders" to return name of every list'
    ),
    # ── System Events — generic "press a key" (any frontmost app) ─
    ("system events", "keystroke"): (
        'tell application "System Events" to keystroke "{value}"'
    ),
    ("system events", "key_code"): (
        # Numeric key codes (Return=36, Tab=48, Escape=53, ...).
        'tell application "System Events" to key code {value}'
    ),
    # ── Generic probes (any app — app=``*``) ─────────────────────
    ("*", "is_running"): (
        'tell application "System Events" to return '
        '(name of (processes whose name is "{value}")) as string'
    ),
    ("*", "front_app"): (
        'tell application "System Events" to return name of first '
        'process whose frontmost is true'
    ),
    ("*", "activate"): (
        # Bring an app to the front without opening a new window —
        # equivalent to clicking its Dock icon. Use ``open`` when
        # you also want to launch it if not running; ``activate``
        # only raises a running app.
        'tell application "{value}" to activate'
    ),
}


def _supported_apps() -> set[str]:
    """Apps with at least one dispatch entry."""
    return {app for app, _ in _DISPATCH if app != "*"}


class AppleScriptEngine:
    """Per-app dispatch over ``osascript``. Top of the ladder when
    the target app is in the table."""

    name: str = _NAME
    priority: int = _PRIORITY

    def is_available(self) -> tuple[bool, str]:
        if shutil.which("osascript") is None:
            return False, "osascript not on PATH (macOS-only utility)"
        return True, "ready"

    def can_handle(self, action: Action) -> float:
        """Confidence is 1.0 if the (app, kind) pair is in the
        dispatch table, otherwise 0.0. Generic wildcards (e.g.
        ``is_running``) hit on app=``"*"``."""
        kind = (action.kind or "").lower()
        app = (action.target or action.args.get("app") or "").lower()
        if (app, kind) in _DISPATCH or ("*", kind) in _DISPATCH:
            return 1.0
        return 0.0

    def execute(self, action: Action) -> EngineResult:
        started = time.perf_counter()
        kind = (action.kind or "").lower()
        app = (action.target or action.args.get("app") or "").lower()
        template = _DISPATCH.get((app, kind)) or _DISPATCH.get(("*", kind))
        if template is None:
            return EngineResult(
                ok=False, engine=_NAME,
                error=f"no AppleScript template for app={app!r} kind={kind!r}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        # The template's ``{value}`` slot is filled from the action's
        # ``args`` — but the model / goal parser uses different keys
        # depending on the verb (``value`` for set_value, ``label``
        # for press, ``text`` for type, ``url`` for open_url). We
        # accept any of the common keys so the engine doesn't care
        # which the caller used.
        args = action.args
        value = str(
            args.get("value")
            or args.get("label")
            or args.get("text")
            or args.get("url")
            or args.get("path")
            or args.get("key")
            or ""
        )
        # Defensive: escape any literal double-quote in ``value`` so
        # the template renders without breaking out of its string.
        safe_value = value.replace('"', r'\"')
        script = template.replace("{value}", safe_value)
        try:
            out = subprocess.run(
                ["osascript", "-e", script],
                check=False, capture_output=True, text=True, timeout=10,
            )
        except Exception as exc:  # noqa: BLE001 — engine must never raise
            return EngineResult(
                ok=False, engine=_NAME,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
            )
        elapsed = (time.perf_counter() - started) * 1000.0
        if out.returncode != 0:
            return EngineResult(
                ok=False, engine=_NAME,
                error=(out.stderr or out.stdout or "osascript failed").strip(),
                elapsed_ms=elapsed,
            )
        return EngineResult(
            ok=True, engine=_NAME,
            result={"stdout": out.stdout.strip(), "app": app, "kind": kind},
            elapsed_ms=elapsed,
        )


__all__ = ["AppleScriptEngine"]
