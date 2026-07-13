"""System control — one tool, ``system_control``, over five actions:
volume, brightness, dark_mode, do_not_disturb (all via ``osascript`` /
``defaults``), and prevent_sleep (via a detached, self-expiring
``caffeinate``). EXTERNAL_EFFECT — these change the host's live state,
not just the workspace.

  * volume(0-100)       — AppleScript ``set volume output volume``.
  * brightness(0-100)   — no public AppleScript verb exists for
    absolute display brightness; this shells out to the third-party
    ``brightness`` CLI (``brew install brightness``) if present, else
    returns an actionable error rather than silently no-op-ing.
  * dark_mode(on/off)   — AppleScript appearance preferences.
  * do_not_disturb(on/off) — best-effort via the legacy
    ``com.apple.notificationcenterui doNotDisturb`` preference key +
    a NotificationCenter restart. macOS Sonoma+ Focus modes may not
    honor this (Apple replaced the old DND toggle with Focus and never
    shipped a public scripting API for it) — the result says so; a
    Shortcuts automation via ``run_shortcut`` is the more reliable path
    on newer systems.
  * prevent_sleep(minutes) — a detached ``caffeinate -t <seconds>`` that
    exits on its own; no separate "stop" call needed.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 8
_VALID_ACTIONS = ("volume", "brightness", "dark_mode", "do_not_disturb", "prevent_sleep")


def _not_macos_error() -> dict[str, Any]:
    return {"error": f"system_control is only available on macOS (got {platform.system()})"}


def _run_osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], check=False,
                           capture_output=True, text=True, timeout=_TIMEOUT_S)


def _clamp_percent(value: Any, default: int = 50) -> int:
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        v = default
    return max(0, min(100, v))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in ("on", "true", "1", "yes", "enable", "enabled")


def _set_volume(value: Any) -> dict[str, Any]:
    pct = _clamp_percent(value, default=50)
    try:
        out = _run_osascript(f"set volume output volume {pct}")
    except Exception as exc:  # noqa: BLE001
        return {"changed": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or "osascript failed").strip()}
    return {"changed": True, "action": "volume", "value": pct}


def _set_brightness(value: Any) -> dict[str, Any]:
    pct = _clamp_percent(value, default=50)
    brightness_bin = shutil.which("brightness")
    if brightness_bin is None:
        return {
            "changed": False,
            "error": ("no public AppleScript verb sets absolute display brightness — "
                      "install the `brightness` CLI (`brew install brightness`) as the "
                      "backend for this action."),
        }
    try:
        out = subprocess.run([brightness_bin, str(round(pct / 100.0, 2))],
                              check=False, capture_output=True, text=True, timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return {"changed": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or "brightness failed").strip()}
    return {"changed": True, "action": "brightness", "value": pct}


def _set_dark_mode(value: Any) -> dict[str, Any]:
    on = _as_bool(value)
    script = (
        'tell application "System Events" to tell appearance preferences '
        f'to set dark mode to {"true" if on else "false"}'
    )
    try:
        out = _run_osascript(script)
    except Exception as exc:  # noqa: BLE001
        return {"changed": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or "osascript failed").strip()}
    return {"changed": True, "action": "dark_mode", "value": on}


def _set_do_not_disturb(value: Any) -> dict[str, Any]:
    on = _as_bool(value)
    try:
        pref = subprocess.run(
            ["defaults", "-currentHost", "write", "com.apple.notificationcenterui",
             "doNotDisturb", "-boolean", "true" if on else "false"],
            check=False, capture_output=True, text=True, timeout=_TIMEOUT_S,
        )
        subprocess.run(["killall", "NotificationCenter"], check=False,
                        capture_output=True, text=True, timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return {"changed": False, "error": f"{type(exc).__name__}: {exc}"}
    if pref.returncode != 0:
        return {"changed": False, "error": (pref.stderr or "defaults write failed").strip()}
    return {
        "changed": True, "action": "do_not_disturb", "value": on,
        "note": ("best-effort via a legacy preference key — macOS Sonoma+ Focus modes "
                 "may not honor this; a Shortcuts automation via run_shortcut is the "
                 "more reliable path on newer systems"),
    }


def _prevent_sleep(minutes: Any) -> dict[str, Any]:
    try:
        mins = max(1, int(float(minutes)))
    except (TypeError, ValueError):
        return {"changed": False, "error": f"invalid minutes: {minutes!r}"}
    seconds = mins * 60
    if shutil.which("caffeinate") is None:
        return {"changed": False, "error": "caffeinate not on PATH (macOS-only utility)"}
    try:
        proc = subprocess.Popen(
            ["caffeinate", "-i", "-t", str(seconds)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"changed": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"changed": True, "action": "prevent_sleep", "minutes": mins, "pid": proc.pid,
             "note": "auto-expires after the given minutes — no stop call needed"}


_DISPATCH = {
    "volume": _set_volume,
    "brightness": _set_brightness,
    "dark_mode": _set_dark_mode,
    "do_not_disturb": _set_do_not_disturb,
    "prevent_sleep": _prevent_sleep,
}


def system_control(action: str, value: Any = None) -> dict[str, Any]:
    """Dispatch a system-control ``action`` — see the module docstring
    for the exact backend each one uses."""
    action_clean = (action or "").strip().lower()
    if action_clean not in _VALID_ACTIONS:
        return {"changed": False,
                 "error": f"unknown action {action!r} — use one of {_VALID_ACTIONS}"}
    if platform.system() != "Darwin":
        return {"changed": False, **_not_macos_error()}
    return _DISPATCH[action_clean](value)


# ── Agent-facing tool wrapper ────────────────────────────────────────


@register_tool_from_function(name="system_control")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="system_control",
               operation="system_control",
               summary="change a live system setting")
def _t_system_control(action: str, value: Any = None) -> dict:
    """Change a live macOS system setting. `action` is one of:
      • "volume" — `value` 0-100.
      • "brightness" — `value` 0-100 (needs the `brightness` CLI;
        actionable error with the install command if missing).
      • "dark_mode" — `value` on/off (or true/false).
      • "do_not_disturb" — `value` on/off; best-effort, may not hold on
        macOS Sonoma+ (see module notes) — say so if the result flags it.
      • "prevent_sleep" — `value` = minutes to keep the Mac awake;
        self-expires, no separate stop call.
    EXTERNAL EFFECT — confirms like any other tier-2 action. Returns
    {changed: True, action, ...} or {changed: False, error}."""
    return system_control(action=action, value=value)


__all__ = ["system_control"]
