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
  * Calculator — open / press (typed input) / read result
  * Notes — create note, append, list
  * Safari — open URL, run JS, current URL/title
  * Mail — count unread, new draft
  * Finder — open path, reveal item
  * Music — play / pause / next / volume
  * TextEdit / Pages / Keynote / Numbers / Word / PowerPoint /
    Excel — new document (with initial text/title), save to path
  * ANY app — window management (list / bounds / move / resize /
    minimize / fullscreen / zoom / close), save_doc, quit_app,
    is_running, activate

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
        # ``value`` is typed keyboard input ("5*5=" — use * and /,
        # not × ÷). Keystrokes work on every macOS; clicking buttons
        # by label broke when Sequoia+ stopped naming the AX buttons.
        'tell application "Calculator" to activate\n'
        'delay 0.3\n'
        'tell application "System Events" to keystroke "{value}"'
    ),
    ("calculator", "read_result"): (
        # Modern Calculator nests the display; older ones don't. Try
        # the deep path first, fall back to the legacy one.
        'tell application "System Events" to tell process "Calculator"\n'
        '  try\n'
        '    return value of static text 1 of scroll area 2 of group 1 '
        'of group 1 of splitter group 1 of group 1 of window 1\n'
        '  on error\n'
        '    return value of static text 1 of group 1 of window 1\n'
        '  end try\n'
        'end tell'
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
    # ── Window management (any app — target is the process name) ──
    # ``{app}`` = the app/process name; ``{value}`` = geometry where
    # needed ("x, y" for move, "width, height" for resize). Block
    # form is required: the chained `tell X to set ...` one-liner
    # misparses (-10006 "Can't set process").
    ("*", "window_list"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  return name of every window\n'
        'end tell'
    ),
    ("*", "window_bounds"): (
        # → "x, y, w, h"
        'tell application "System Events" to tell process "{app}"\n'
        '  set p to position of window 1\n'
        '  set s to size of window 1\n'
        '  return (item 1 of p as string) & ", " & (item 2 of p) '
        '& ", " & (item 1 of s) & ", " & (item 2 of s)\n'
        'end tell'
    ),
    ("*", "move_window"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  set position of window 1 to {{value}}\n'
        'end tell'
    ),
    ("*", "resize_window"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  set size of window 1 to {{value}}\n'
        'end tell'
    ),
    ("*", "minimize"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  set value of attribute "AXMinimized" of window 1 to true\n'
        'end tell'
    ),
    ("*", "unminimize"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  set value of attribute "AXMinimized" of window 1 to false\n'
        'end tell'
    ),
    ("*", "fullscreen"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  set value of attribute "AXFullScreen" of window 1 to true\n'
        'end tell'
    ),
    ("*", "exit_fullscreen"): (
        'tell application "System Events" to tell process "{app}"\n'
        '  set value of attribute "AXFullScreen" of window 1 to false\n'
        'end tell'
    ),
    ("*", "zoom_window"): (
        # The green button's non-fullscreen "zoom" (fit to content).
        'tell application "System Events" to tell window 1 of process '
        '"{app}" to click (first button whose subrole is "AXZoomButton")'
    ),
    ("*", "close_window"): (
        'tell application "System Events" to tell window 1 of process '
        '"{app}" to click (first button whose subrole is "AXCloseButton")'
    ),
    # ── Documents — day-to-day authoring apps ─────────────────────
    # ``{value}`` = the initial text/title. Every "new_*" leaves the
    # app frontmost with an unsaved document; pair with ("*",
    # "save_doc") — value = absolute POSIX path — to write it out.
    ("textedit", "new_doc"): (
        'tell application "TextEdit"\n'
        '  activate\n'
        '  set d to make new document\n'
        '  set text of d to "{value}"\n'
        'end tell'
    ),
    ("pages", "new_doc"): (
        'tell application "Pages"\n'
        '  activate\n'
        '  set d to make new document\n'
        '  set body text of d to "{value}"\n'
        'end tell'
    ),
    ("keynote", "new_presentation"): (
        # ``value`` becomes the title of the opening slide.
        'tell application "Keynote"\n'
        '  activate\n'
        '  set d to make new document\n'
        '  tell slide 1 of d to set object text of default title item '
        'to "{value}"\n'
        'end tell'
    ),
    ("numbers", "new_spreadsheet"): (
        'tell application "Numbers"\n'
        '  activate\n'
        '  make new document\n'
        'end tell'
    ),
    # Office apps reject `make new ...` until fully launched — retry
    # until ready (fast when already running, ~1s/try when cold).
    ("microsoft word", "new_doc"): (
        'tell application "Microsoft Word" to activate\n'
        'repeat with i from 1 to 15\n'
        '  try\n'
        '    tell application "Microsoft Word" to set d to make new document\n'
        '    exit repeat\n'
        '  on error\n'
        '    delay 1\n'
        '  end try\n'
        'end repeat\n'
        'tell application "Microsoft Word" to set content of '
        'text object of d to "{value}"'
    ),
    ("microsoft word", "save_doc"): (
        'tell application "Microsoft Word" to save as active document '
        'file name "{value}"'
    ),
    ("microsoft powerpoint", "new_presentation"): (
        'tell application "Microsoft PowerPoint" to activate\n'
        'repeat with i from 1 to 15\n'
        '  try\n'
        '    tell application "Microsoft PowerPoint" to make new presentation\n'
        '    exit repeat\n'
        '  on error\n'
        '    delay 1\n'
        '  end try\n'
        'end repeat'
    ),
    ("microsoft powerpoint", "save_doc"): (
        'tell application "Microsoft PowerPoint" to save active '
        'presentation in "{value}"'
    ),
    ("microsoft excel", "new_workbook"): (
        'tell application "Microsoft Excel" to activate\n'
        'repeat with i from 1 to 15\n'
        '  try\n'
        '    tell application "Microsoft Excel" to make new workbook\n'
        '    exit repeat\n'
        '  on error\n'
        '    delay 1\n'
        '  end try\n'
        'end repeat'
    ),
    ("microsoft excel", "save_doc"): (
        'tell application "Microsoft Excel" to save workbook as '
        'active workbook filename "{value}"'
    ),
    ("*", "save_doc"): (
        # Save the front document to an absolute POSIX path. NOTE:
        # sandboxed apps (App Store Office) pop a one-time "Grant File
        # Access" dialog for folders the user hasn't granted — the call
        # blocks until answered. Prefer ~/Documents or ~/Desktop.
        'tell application "{app}" to save front document in '
        '(POSIX file "{value}")'
    ),
    ("*", "quit_app"): (
        'tell application "{app}" to quit'
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
        # ``{app}`` carries the target app's process name for templates
        # that need BOTH an app and a value (window management).
        safe_app = str(action.target or args.get("app") or "").replace('"', r'\"')
        script = template.replace("{value}", safe_value).replace("{app}", safe_app)
        try:
            out = subprocess.run(
                ["osascript", "-e", script],
                # 30s: document apps (Word, Pages) can cold-start
                # slower than the 10s the quick probes need.
                check=False, capture_output=True, text=True, timeout=30,
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
        # Calculator (and other AX reads) prefix values with invisible
        # bidi marks — strip them so "25" compares equal to "25".
        stdout = out.stdout.strip().replace("\u200e", "").replace("\u200f", "")
        return EngineResult(
            ok=True, engine=_NAME,
            result={"stdout": stdout, "app": app, "kind": kind},
            elapsed_ms=elapsed,
        )


__all__ = ["AppleScriptEngine"]
