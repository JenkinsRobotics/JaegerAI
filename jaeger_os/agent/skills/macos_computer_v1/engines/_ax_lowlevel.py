"""macOS background-automation engine — focus-preserving desktop control.

The `computer_*` tools in :mod:`computer_use` drive the Mac the *loud*
way: CoreGraphics mouse events move the real cursor, and `tell app to
activate` steals focus. That is right when the user wants to *see* it
happen — but wrong for "rearrange those windows behind my back" or
"skip the track without leaving my editor".

This module is the quiet complement. It treats the desktop as an
**object tree**, not a canvas of pixels:

  * **Windows** are moved / resized by setting the Accessibility
    attributes ``AXPosition`` / ``AXSize`` directly on the window
    element — no drag, no cursor, the window never comes forward.
  * **Buttons** are pressed by finding the element in the app's
    Accessibility tree and invoking ``AXPress`` — no pointer travel,
    works on a window that is not frontmost.
  * **Browser pages** are scripted by sending the JavaScript straight to
    Chrome / Safari over Apple Events, without activating the browser.

It never touches ``AXMain`` / ``AXFocused`` and never injects a
hardware pointer event — the user's cursor and keyboard focus stay
entirely theirs. macOS-specific by nature; a future Linux/Windows host
would need its own engine, which is why this lives in its own module.

Requires PyObjC (`pyobjc-framework-ApplicationServices` / `-Quartz` /
`-Cocoa`) and the host process holding **Accessibility** permission.
Both are checked by :func:`is_available` — every tool fails clean with a
remediation message rather than throwing.
"""

from __future__ import annotations

import subprocess
from typing import Any

# AXError codes worth naming (the full set is large; these are the ones
# a caller can act on).
_AX_SUCCESS = 0
_AX_API_DISABLED = -25211          # process lacks Accessibility permission
_AX_NO_VALUE = -25212
_AX_ATTR_UNSUPPORTED = -25205
_AX_CANNOT_COMPLETE = -25204
_AX_ERROR_NAMES = {
    _AX_API_DISABLED: "Accessibility API disabled — grant the host process "
                      "Accessibility permission",
    _AX_NO_VALUE: "no value for that attribute",
    _AX_ATTR_UNSUPPORTED: "the element does not support that attribute",
    _AX_CANNOT_COMPLETE: "the app did not respond (it may be busy or hung)",
}

# Tree-walk bounds — a runaway AX tree must never hang a turn.
_MAX_DEPTH = 60
_MAX_NODES = 6000


# ── availability ─────────────────────────────────────────────────────


def is_available() -> tuple[bool, str]:
    """``(ready, detail)`` — PyObjC importable *and* Accessibility granted.

    PyObjC is an optional backend registered with
    :mod:`jaeger_os.core.models.lazy_deps` as ``macos.background``. When
    ``security.allow_lazy_installs`` is on, a missing PyObjC is installed
    automatically on first use; otherwise ``detail`` carries the exact
    ``pip install`` to run. The Accessibility-permission check cannot be
    automated — only the user can grant it."""
    try:
        from jaeger_os.core.models import lazy_deps
        lazy_deps.ensure("macos.background")
    except Exception as exc:  # noqa: BLE001 — FeatureUnavailable or import path
        return False, str(exc)
    import ApplicationServices as _AX
    if not _AX.AXIsProcessTrusted():
        return False, ("the host process lacks Accessibility permission — "
                       "grant it under System Settings > Privacy & Security "
                       "> Accessibility, then restart Jaeger")
    return True, "ready"


def _unavailable(detail: str) -> dict[str, Any]:
    return {"ok": False, "error": detail, "needs_permission": True}


def _ax_err(code: int) -> str:
    return _AX_ERROR_NAMES.get(code, f"Accessibility error {code}")


# ── AX attribute helpers ─────────────────────────────────────────────


def _copy_attr(element: Any, attr: str) -> Any:
    """The element's ``attr`` value, or ``None`` on any error."""
    import ApplicationServices as _AX
    err, val = _AX.AXUIElementCopyAttributeValue(element, attr, None)
    return val if err == _AX_SUCCESS else None


def _running_apps() -> list[dict[str, Any]]:
    """Every running app with a UI — name, bundle id, PID."""
    import AppKit
    out: list[dict[str, Any]] = []
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        # 1 == NSApplicationActivationPolicyRegular (has a Dock presence).
        if app.activationPolicy() != 0:
            out.append({
                "name": str(app.localizedName() or ""),
                "bundle_id": str(app.bundleIdentifier() or ""),
                "pid": int(app.processIdentifier()),
            })
    return out


def _resolve_pid(app: str) -> int | None:
    """Map an app name or bundle id to a PID (case-insensitive)."""
    needle = (app or "").strip().lower()
    if not needle:
        return None
    for row in _running_apps():
        if needle in (row["name"].lower(), row["bundle_id"].lower()):
            return row["pid"]
    for row in _running_apps():            # looser: substring on the name
        if needle in row["name"].lower():
            return row["pid"]
    return None


def list_running_apps() -> dict[str, Any]:
    """Every running UI app with its PID — the entry point for targeting."""
    ready, detail = is_available()
    if not ready:
        return _unavailable(detail)
    return {"ok": True, "apps": _running_apps()}


# ── windows ──────────────────────────────────────────────────────────


def _windows_of(pid: int) -> list[Any] | None:
    import ApplicationServices as _AX
    app = _AX.AXUIElementCreateApplication(pid)
    return _copy_attr(app, _AX.kAXWindowsAttribute)


def _point_size(window: Any) -> tuple[tuple[float, float] | None,
                                      tuple[float, float] | None]:
    """Read a window's current ``(x, y)`` and ``(w, h)``."""
    import ApplicationServices as _AX
    pos = size = None
    raw_pos = _copy_attr(window, _AX.kAXPositionAttribute)
    raw_size = _copy_attr(window, _AX.kAXSizeAttribute)
    if raw_pos is not None:
        ok, pt = _AX.AXValueGetValue(raw_pos, _AX.kAXValueTypeCGPoint, None)
        if ok:
            pos = (float(pt.x), float(pt.y))
    if raw_size is not None:
        ok, sz = _AX.AXValueGetValue(raw_size, _AX.kAXValueTypeCGSize, None)
        if ok:
            size = (float(sz.width), float(sz.height))
    return pos, size


def list_windows(app: str) -> dict[str, Any]:
    """Every window of ``app`` — index, title, current position + size.

    The index is what :func:`move_window` / :func:`resize_window` take."""
    ready, detail = is_available()
    if not ready:
        return _unavailable(detail)
    import ApplicationServices as _AX
    pid = _resolve_pid(app)
    if pid is None:
        return {"ok": False, "error": f"no running app matching {app!r}"}
    windows = _windows_of(pid)
    if windows is None:
        return {"ok": False, "error": f"could not read {app}'s windows "
                                      f"({_ax_err(_AX_CANNOT_COMPLETE)})"}
    rows: list[dict[str, Any]] = []
    for i, win in enumerate(windows):
        pos, size = _point_size(win)
        rows.append({
            "index": i,
            "title": str(_copy_attr(win, _AX.kAXTitleAttribute) or ""),
            "position": list(pos) if pos else None,
            "size": list(size) if size else None,
        })
    return {"ok": True, "app": app, "pid": pid, "windows": rows}


def _set_window(app: str, window_index: int, attr: str, value_type: int,
                value: Any, action: str) -> dict[str, Any]:
    ready, detail = is_available()
    if not ready:
        return _unavailable(detail)
    import ApplicationServices as _AX
    pid = _resolve_pid(app)
    if pid is None:
        return {"ok": False, "error": f"no running app matching {app!r}"}
    windows = _windows_of(pid)
    if not windows:
        return {"ok": False, "error": f"{app} has no readable windows"}
    if not 0 <= window_index < len(windows):
        return {"ok": False, "error": f"window index {window_index} out of "
                                      f"range (0..{len(windows) - 1})"}
    ax_value = _AX.AXValueCreate(value_type, value)
    if ax_value is None:
        return {"ok": False, "error": "could not build the AX value"}
    err = _AX.AXUIElementSetAttributeValue(windows[window_index], attr, ax_value)
    if err != _AX_SUCCESS:
        return {"ok": False, "error": f"{action} failed — {_ax_err(err)}"}
    return {"ok": True, "action": action, "app": app,
            "window_index": window_index}


def move_window(app: str, x: float, y: float,
                window_index: int = 0) -> dict[str, Any]:
    """Move a window to ``(x, y)`` in screen coordinates — silently.

    The window does not come forward and the cursor does not move."""
    ready, detail = is_available()
    if not ready:
        return _unavailable(detail)
    import Quartz
    res = _set_window(app, window_index, _ax_pos_attr(), _ax_point_type(),
                      Quartz.CGPointMake(float(x), float(y)), "move_window")
    if res.get("ok"):
        res["position"] = [float(x), float(y)]
    return res


def resize_window(app: str, width: float, height: float,
                  window_index: int = 0) -> dict[str, Any]:
    """Resize a window to ``width`` x ``height`` — silently, in place."""
    ready, detail = is_available()
    if not ready:
        return _unavailable(detail)
    import Quartz
    res = _set_window(app, window_index, _ax_size_attr(), _ax_size_type(),
                      Quartz.CGSizeMake(float(width), float(height)),
                      "resize_window")
    if res.get("ok"):
        res["size"] = [float(width), float(height)]
    return res


# Small indirections so the module imports even without PyObjC present
# (the constants are only touched once a tool actually runs).
def _ax_pos_attr() -> str:
    import ApplicationServices as _AX
    return _AX.kAXPositionAttribute


def _ax_size_attr() -> str:
    import ApplicationServices as _AX
    return _AX.kAXSizeAttribute


def _ax_point_type() -> int:
    import ApplicationServices as _AX
    return _AX.kAXValueTypeCGPoint


def _ax_size_type() -> int:
    import ApplicationServices as _AX
    return _AX.kAXValueTypeCGSize


# ── press an element (background click) ──────────────────────────────


def _walk(element: Any, want_role: str, needle: str,
          depth: int, budget: list[int]) -> Any:
    """Depth/node-bounded search for the first matching element.

    Match strategy — first hit wins (depth-first). The needle is
    matched against four attributes in priority order:

      * ``AXTitle``       — the obvious label
      * ``AXDescription`` — fallback label set by accessibility tooling
      * ``AXValue``       — Calculator-style: digit buttons carry the
                            digit here, not in the title
      * ``AXIdentifier``  — developer-set hook; uncommon but cheap

    The exact match (case-insensitive) of any of these is enough. A
    substring match on title/desc is also accepted to handle apps
    that use "5 — five" or similar verbose labels."""
    import ApplicationServices as _AX
    if depth > _MAX_DEPTH or budget[0] <= 0:
        return None
    budget[0] -= 1
    role = str(_copy_attr(element, _AX.kAXRoleAttribute) or "")
    title = str(_copy_attr(element, _AX.kAXTitleAttribute) or "")
    desc = str(_copy_attr(element, "AXDescription") or "")
    value = str(_copy_attr(element, _AX.kAXValueAttribute) or "")
    ident = str(_copy_attr(element, "AXIdentifier") or "")
    role_ok = (not want_role) or want_role.lower() in role.lower()
    needle_lc = (needle or "").lower()
    text_ok = (not needle) or (
        # Exact match on any of the four attributes.
        title.lower() == needle_lc or desc.lower() == needle_lc
        or value.lower() == needle_lc or ident.lower() == needle_lc
        # Substring on title / description for verbose labels.
        or (needle_lc and needle_lc in title.lower())
        or (needle_lc and needle_lc in desc.lower())
    )
    if role_ok and text_ok and (want_role or needle):
        return element
    for child in (_copy_attr(element, _AX.kAXChildrenAttribute) or []):
        hit = _walk(child, want_role, needle, depth + 1, budget)
        if hit is not None:
            return hit
    return None


def press_element(app: str, label: str, role: str = "") -> dict[str, Any]:
    """Press the element of ``app`` whose title/description matches
    ``label`` — via ``AXPress``, with no cursor movement and no focus
    change. ``role`` ("AXButton", "AXMenuItem", …) narrows the search."""
    ready, detail = is_available()
    if not ready:
        return _unavailable(detail)
    import ApplicationServices as _AX
    if not (label or role):
        return {"ok": False, "error": "press needs a label or a role"}
    pid = _resolve_pid(app)
    if pid is None:
        return {"ok": False, "error": f"no running app matching {app!r}"}
    app_el = _AX.AXUIElementCreateApplication(pid)
    target = _walk(app_el, role, label, 0, [_MAX_NODES])
    if target is None:
        return {"ok": False, "error": f"no element matching role={role!r} "
                                      f"label={label!r} in {app}"}
    err = _AX.AXUIElementPerformAction(target, _AX.kAXPressAction)
    if err != _AX_SUCCESS:
        return {"ok": False, "error": f"press failed — {_ax_err(err)}"}
    return {"ok": True, "action": "press_element", "app": app, "label": label}


# ── non-activating browser JavaScript ────────────────────────────────


def run_background_browser_js(js: str, browser: str = "Google Chrome",
                              window_index: int = 1,
                              tab_index: int = 1) -> dict[str, Any]:
    """Run ``js`` in a browser tab over Apple Events — without activating
    the browser. Chrome and Safari both require *Allow JavaScript from
    Apple Events* to be enabled (Chrome: View > Developer; Safari:
    Develop menu); a clear error is returned when it is off."""
    js = (js or "").strip()
    if not js:
        return {"ok": False, "error": "no JavaScript given"}
    name = (browser or "Google Chrome").strip()
    # JS → AppleScript string literal: only backslash and quote need
    # escaping. The script is passed as an argv item (no shell), so there
    # is no second layer of shell escaping to get wrong.
    esc = js.replace("\\", "\\\\").replace('"', '\\"')
    if name.lower() == "safari":
        script = (f'tell application "Safari" to do JavaScript "{esc}" '
                  f'in tab {tab_index} of window {window_index}')
    else:
        script = (f'tell application "{name}" to execute '
                  f'tab {tab_index} of window {window_index} '
                  f'javascript "{esc}"')
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=20)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "error": f"osascript failed: {exc}"}
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "JavaScript" in err and ("turned off" in err or "not allowed" in err
                                    or "disabled" in err.lower()):
            return {"ok": False,
                    "error": f"{name} blocks JavaScript from Apple Events — "
                             "enable it in the browser's Developer settings",
                    "needs_permission": True}
        return {"ok": False, "error": err or "browser scripting failed"}
    return {"ok": True, "action": "browser_js", "browser": name,
            "result": (proc.stdout or "").strip()}


__all__ = [
    "is_available",
    "list_running_apps",
    "list_windows",
    "move_window",
    "resize_window",
    "press_element",
    "run_background_browser_js",
]
