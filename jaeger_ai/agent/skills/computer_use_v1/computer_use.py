"""computer_use — drive any macOS app through the accessibility tree.

Jaeger-OS's flagship skill. "Using a computer" is a *composed* capability
— perceive the screen, find an element, act, verify — not a primitive,
so it is a skill, not a built-in tool.

Grounding is **accessibility-tree first**: ``read_screen`` returns the
on-screen UI elements (from macOS System Events) with their screen
coordinates; ``click`` then acts on a coordinate. No vision model is
needed to find a button.

Zero extra dependencies — everything routes through the macOS built-ins
``osascript`` (AppleScript / System Events) and ``screencapture``. The
module imports only the standard library so its smoke test can load it
standalone; the jaeger_os imports happen lazily inside ``register()``.

SAFETY: the manipulation tools (``click``, ``type_text``, ``press_key``,
``menu_select``) are gated at EXTERNAL_EFFECT — every call routes through
the confirmation provider. ``screenshot`` / ``read_screen`` / ``open_app``
are READ_ONLY-class. macOS also requires the user to grant the host
process **Accessibility** (and **Screen Recording** for screenshots)
permission once, in System Settings → Privacy & Security.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

_IS_MAC = platform.system() == "Darwin"

# Named non-character keys → macOS virtual key codes.
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "esc": 53, "left": 123, "right": 124,
    "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116,
    "pagedown": 121, "f1": 122, "f2": 120, "f3": 99, "f4": 118,
}
_MODIFIERS = {
    "cmd": "command down", "command": "command down",
    "shift": "shift down", "option": "option down", "alt": "option down",
    "control": "control down", "ctrl": "control down",
}

# read_screen — dump the frontmost window's UI elements + their geometry.
# Capped iteration keeps it bounded on a complex window.
_READ_SCREEN_SCRIPT = r'''
tell application "System Events"
	try
		set proc to first process whose frontmost is true
	on error
		return "ERROR: no frontmost process"
	end try
	set out to "app: " & (name of proc) & linefeed
	try
		set win to front window of proc
		set out to out & "window: " & (name of win) & linefeed
		set els to entire contents of win
		set n to 0
		repeat with el in els
			if n is greater than 60 then exit repeat
			try
				set r to (role of el) as text
				set nm to ""
				try
					set nm to (name of el) as text
				end try
				set ds to ""
				try
					set ds to (description of el) as text
				end try
				set px to "?"
				set py to "?"
				set sw to "0"
				set sh to "0"
				try
					set pos to position of el
					set px to (item 1 of pos) as text
					set py to (item 2 of pos) as text
					set sz to size of el
					set sw to (item 1 of sz) as text
					set sh to (item 2 of sz) as text
				end try
				set out to out & r & " ||| " & nm & " ||| " & ds & " ||| " & px & " ||| " & py & " ||| " & sw & " ||| " & sh & linefeed
				set n to n + 1
			end try
		end repeat
	on error errMsg
		set out to out & "window-read-error: " & errMsg & linefeed
	end try
	return out
end tell
'''


def _esc(text: str) -> str:
    """Escape a Python string for use inside an AppleScript "..." literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _osascript(script: str, timeout: float = 20.0) -> tuple[bool, str]:
    """Run an AppleScript via ``osascript``. Returns (ok, output-or-error)."""
    if not _IS_MAC:
        return False, "computer_use is macOS-only"
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"osascript timed out after {timeout:.0f}s"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "assistive access" in err or "-25211" in err or "1002" in err:
            return False, (
                "macOS Accessibility permission is required. Grant it in "
                "System Settings → Privacy & Security → Accessibility for "
                "the app running Jaeger-OS (Terminal / your IDE), then retry."
            )
        return False, err or "osascript failed"
    return True, (proc.stdout or "").strip()


# ── perceive ─────────────────────────────────────────────────────────


def screenshot(path: str = "screen.png") -> dict[str, Any]:
    """Capture the screen to a PNG under the instance's skills/ directory."""
    from jaeger_ai.core.context import (  # lazy — keep module import-clean
        SandboxError, _require_layout, _resolve_under,
    )
    if not _IS_MAC:
        return {"ok": False, "error": "computer_use is macOS-only"}
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        return {"ok": False, "error": str(exc)}
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["screencapture", "-x", str(target)], capture_output=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode != 0 or not target.exists():
        return {"ok": False, "error": ("screencapture failed — the host "
                "process may need Screen Recording permission.")}
    return {"ok": True, "path": str(target.relative_to(layout.root)),
            "bytes": target.stat().st_size}


def _parse_screen(raw: str) -> dict[str, Any]:
    """Parse the read_screen AppleScript output into structured elements."""
    app = window = ""
    elements: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if line.startswith("app: "):
            app = line[5:].strip()
        elif line.startswith("window: "):
            window = line[8:].strip()
        elif "|||" in line:
            # Split on the bare delimiter and strip — robust to however
            # AppleScript spaced an empty field.
            parts = [p.strip() for p in line.split("|||")]
            if len(parts) != 7:
                continue
            role, name, desc, px, py, sw, sh = parts
            el: dict[str, Any] = {"role": role, "name": name,
                                  "description": desc}
            try:  # clickable point = element centre
                x, y = int(px), int(py)
                w, h = int(sw), int(sh)
                el["x"] = x + w // 2
                el["y"] = y + h // 2
            except ValueError:
                pass
            elements.append(el)
    return {"app": app, "window": window, "elements": elements,
            "count": len(elements)}


def read_screen() -> dict[str, Any]:
    """Read the frontmost window's UI elements + their click points.

    The accessibility-tree grounding primitive: returns ``{app, window,
    elements}`` where each element has ``role``, ``name``, ``description``
    and (when available) an ``x`` / ``y`` centre point you pass to
    ``click``."""
    ok, out = _osascript(_READ_SCREEN_SCRIPT)
    if not ok:
        return {"ok": False, "error": out}
    if out.startswith("ERROR:"):
        return {"ok": False, "error": out[6:].strip()}
    return {"ok": True, **_parse_screen(out)}


# ── act ──────────────────────────────────────────────────────────────


def open_app(name: str) -> dict[str, Any]:
    """Launch / focus a macOS application by name (e.g. 'Safari')."""
    clean = (name or "").strip()
    if not clean:
        return {"ok": False, "error": "empty app name"}
    ok, out = _osascript(f'tell application "{_esc(clean)}" to activate')
    if not ok:
        return {"ok": False, "error": out, "app": clean}
    return {"ok": True, "app": clean, "note": f"{clean} is now frontmost"}


def click(x: int, y: int) -> dict[str, Any]:
    """Click at screen coordinate (x, y) — typically an element's centre
    point from ``read_screen``."""
    try:
        xi, yi = int(x), int(y)
    except (TypeError, ValueError):
        return {"ok": False, "error": "x and y must be integers"}
    ok, out = _osascript(
        f"tell application \"System Events\" to click at {{{xi}, {yi}}}"
    )
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "clicked": [xi, yi]}


def type_text(text: str) -> dict[str, Any]:
    """Type text into the focused field (via System Events keystroke)."""
    if not text:
        return {"ok": False, "error": "empty text"}
    ok, out = _osascript(
        f'tell application "System Events" to keystroke "{_esc(text)}"'
    )
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "typed": len(text)}


def _build_press_script(key: str) -> tuple[str | None, str | None]:
    """Pure: resolve a key / chord spec to an AppleScript string, or
    return ``(None, error)``. No OS interaction — unit-testable."""
    clean = (key or "").strip().lower()
    if not clean:
        return None, "empty key"
    parts = [p.strip() for p in clean.split("+") if p.strip()]
    mods = [_MODIFIERS[p] for p in parts[:-1] if p in _MODIFIERS]
    final = parts[-1] if parts else ""
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    if final in _KEY_CODES:
        return (f'tell application "System Events" to key code '
                f"{_KEY_CODES[final]}{using}", None)
    if len(final) == 1:
        return (f'tell application "System Events" to keystroke '
                f'"{_esc(final)}"{using}', None)
    return None, (f"unknown key {key!r} — use a single character or one "
                  "of " + ", ".join(sorted(_KEY_CODES)))


def press_key(key: str) -> dict[str, Any]:
    """Press a key or chord — e.g. 'return', 'tab', 'escape', 'cmd+c',
    'shift+tab'. Character keys combine with cmd/shift/option/control."""
    script, err = _build_press_script(key)
    if err:
        return {"ok": False, "error": err}
    ok, out = _osascript(script)  # type: ignore[arg-type]
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "pressed": (key or "").strip().lower()}


def menu_select(menu: str, item: str) -> dict[str, Any]:
    """Click a menu-bar item in the frontmost app — e.g.
    ``menu_select("File", "New Window")``. Menu paths are stable, so this
    is the most reliable way to drive an app."""
    m, it = (menu or "").strip(), (item or "").strip()
    if not m or not it:
        return {"ok": False, "error": "both menu and item are required"}
    script = (
        'tell application "System Events" to tell '
        '(first process whose frontmost is true) to click '
        f'menu item "{_esc(it)}" of menu "{_esc(m)}" of '
        f'menu bar item "{_esc(m)}" of menu bar 1'
    )
    ok, out = _osascript(script)
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "selected": f"{m} → {it}"}


# ── registration ─────────────────────────────────────────────────────


def register(agent: Any) -> None:
    """Attach the seven computer-use tools to the agent.

    READ_ONLY: screenshot, read_screen, open_app. EXTERNAL_EFFECT (every
    call confirmation-gated): click, type_text, press_key, menu_select."""
    from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

    def _gated(tier: PermissionTier, op: str, summary: str):
        return requires_tier(tier, skill="computer_use", operation=op,
                             summary=summary)

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "screenshot", "capture the screen")
    def computer_screenshot(path: str = "screen.png") -> dict:
        """Capture a screenshot of the Mac's screen to a PNG under skills/.
        Use this to SEE the screen before deciding what to do."""
        return screenshot(path=path)

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "read_screen", "read on-screen UI elements")
    def computer_read_screen() -> dict:
        """Read the frontmost window's clickable UI elements + their
        coordinates (the accessibility tree). Call this to find WHERE to
        click — each element carries an x/y centre point for `computer_click`."""
        return read_screen()

    @agent.tool_plain
    @_gated(PermissionTier.READ_ONLY, "open_app", "launch a macOS app")
    def computer_open_app(name: str) -> dict:
        """Launch or focus a macOS application by name (e.g. 'Safari').
        NOT for opening a website — "open <site> in <browser>" is one
        open_on_host call with the URL, no GUI driving needed. For a
        multi-step GUI task, load the macos-computer-use skill first."""
        return open_app(name=name)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "click", "click the screen")
    def computer_click(x: int, y: int) -> dict:
        """Click at screen coordinate (x, y) — use an element's x/y from
        `computer_read_screen`."""
        return click(x=x, y=y)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "type_text", "type text")
    def computer_type_text(text: str) -> dict:
        """Type text into the currently focused field."""
        return type_text(text=text)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "press_key", "press a key")
    def computer_press_key(key: str) -> dict:
        """Press a key or chord — 'return', 'tab', 'escape', 'cmd+c', etc."""
        return press_key(key=key)

    @agent.tool_plain
    @_gated(PermissionTier.EXTERNAL_EFFECT, "menu_select", "click a menu item")
    def computer_menu_select(menu: str, item: str) -> dict:
        """Click a menu-bar item in the frontmost app — e.g.
        menu='File', item='New Window'. The most reliable way to drive
        an app, since menu names are stable."""
        return menu_select(menu=menu, item=item)
