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

import os
import platform
import re
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 8
_VALID_ACTIONS = ("volume", "brightness", "dark_mode", "do_not_disturb", "prevent_sleep",
                  "lock_screen", "display_off", "open_app", "quit_app", "status")
_APP_NAME_OK = re.compile(r"^[\w .&'+()-]{1,80}$")


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


def _lock_screen(_value: Any = None) -> dict[str, Any]:
    """Lock now. Same call the Control Center lock uses (login.framework
    SACLockScreenImmediate); falls back to sleeping the display, which locks
    when "require password" is immediate."""
    try:
        import ctypes
        login = ctypes.CDLL("/System/Library/PrivateFrameworks/login.framework/Versions/Current/login")
        rc = login.SACLockScreenImmediate()
        if rc == 0:
            return {"changed": True, "action": "lock_screen", "method": "SACLockScreenImmediate"}
    except Exception:  # noqa: BLE001
        pass
    out = subprocess.run(["pmset", "displaysleepnow"], capture_output=True, text=True, timeout=_TIMEOUT_S)
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or "pmset failed").strip()}
    return {"changed": True, "action": "lock_screen", "method": "pmset displaysleepnow",
            "note": "locks when Lock Screen requires the password immediately"}


def _display_off(_value: Any = None) -> dict[str, Any]:
    out = subprocess.run(["pmset", "displaysleepnow"], capture_output=True, text=True, timeout=_TIMEOUT_S)
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or "pmset failed").strip()}
    return {"changed": True, "action": "display_off"}


def _app_name(value: Any) -> str | None:
    name = str(value or "").strip()
    if name.endswith(".app"):
        name = name[:-4]
    return name if _APP_NAME_OK.match(name) else None


def _open_app(value: Any) -> dict[str, Any]:
    name = _app_name(value)
    if not name:
        return {"changed": False, "error": f"give an app name, e.g. Safari (got {value!r})"}
    out = subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=_TIMEOUT_S)
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or f"could not open {name}").strip()}
    return {"changed": True, "action": "open_app", "app": name}


def _quit_app(value: Any) -> dict[str, Any]:
    name = _app_name(value)
    if not name:
        return {"changed": False, "error": f"give an app name, e.g. Safari (got {value!r})"}
    out = _run_osascript(f'tell application "{name}" to quit')
    if out.returncode != 0:
        return {"changed": False, "error": (out.stderr or f"could not quit {name}").strip()}
    return {"changed": True, "action": "quit_app", "app": name}


def mac_status() -> dict[str, Any]:
    """Read-only snapshot: uptime, load, memory pressure, disk, power,
    frontmost app, display and lock state, Wi-Fi. Never changes anything."""
    def run(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT_S).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    status: dict[str, Any] = {"host": platform.node(), "macos": platform.mac_ver()[0]}
    status["uptime"] = run(["uptime"])
    try:
        status["load"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    disk = run(["df", "-h", "/System/Volumes/Data"]).splitlines()
    if len(disk) > 1:
        cols = disk[1].split()
        status["disk"] = {"size": cols[1], "used": cols[2], "free": cols[3], "capacity": cols[4]}
    mem = run(["memory_pressure", "-Q"])
    m = re.search(r"free percentage: (\d+)%", mem)
    if m:
        status["memory_free_percent"] = int(m.group(1))
    status["power"] = run(["pmset", "-g", "batt"]).splitlines()[:2]
    front = _run_osascript('tell application "System Events" to get name of first process whose frontmost is true')
    if front.returncode == 0:
        status["frontmost_app"] = front.stdout.strip()
    ioreg = run(["ioreg", "-n", "IODisplayWrangler", "-r", "-d", "1"])
    m = re.search(r'"CurrentPowerState"=(\d)', ioreg)
    if m:
        status["display_on"] = int(m.group(1)) == 4
    status["screen_locked"] = "CGSSessionScreenIsLocked" in run(["ioreg", "-n", "Root", "-d1", "-a"])
    return status


_DISPATCH = {
    "volume": _set_volume,
    "brightness": _set_brightness,
    "dark_mode": _set_dark_mode,
    "do_not_disturb": _set_do_not_disturb,
    "prevent_sleep": _prevent_sleep,
    "lock_screen": _lock_screen,
    "display_off": _display_off,
    "open_app": _open_app,
    "quit_app": _quit_app,
    "status": lambda _v=None: {"changed": False, "action": "status", **mac_status()},
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


@register_tool_from_function(name="system_control", side_effect="external")
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
      • "lock_screen" — lock the Mac now (no value).
      • "display_off" — put the display to sleep now (no value).
      • "open_app" / "quit_app" — `value` = app name, e.g. "Safari".
      • "status" — read-only snapshot (same as the mac_status tool).
    EXTERNAL EFFECT — confirms like any other tier-2 action. Returns
    {changed: True, action, ...} or {changed: False, error}."""
    return system_control(action=action, value=value)


@register_tool_from_function(name="mac_status", side_effect="read")
def _t_mac_status() -> dict:
    """Read-only Mac status: uptime, load, memory, disk, power, frontmost
    app, whether the display is on and the screen is locked. Use it for
    "how's my Mac?" from any surface, including the phone."""
    return mac_status()


__all__ = ["system_control", "mac_status"]
