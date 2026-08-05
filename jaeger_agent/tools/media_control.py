"""Media control — playback transport over Music.app (always) and
Spotify (if it's running) via AppleScript — same one-round-trip
pattern as ``applescript_engine.py``'s Music dispatch entries.

Picks the target app by what's actually running: Spotify if its
process is up, else Music.app (which AppleScript will launch if it
isn't already running — matching how `open_on_host`/`computer_do`
treat "control the music" as not needing the user to have an app
already open).

Two registered tools, same split as ``host.py``'s
``open_on_host``/``system_status`` pair:

  • ``media_control(action)`` — play / pause / next (``skip`` is
    accepted as an alias) / previous. EXTERNAL_EFFECT.
  • ``now_playing()`` — what's playing right now, no confirmation.
    READ_ONLY.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 8
_TRANSPORT_ACTIONS = ("play", "pause", "next", "skip", "previous")

_ACTION_VERB = {
    "play": "play", "pause": "pause",
    "next": "next track", "skip": "next track",
    "previous": "previous track",
}


def _not_macos_error() -> dict[str, Any]:
    return {"error": f"media_control is only available on macOS (got {platform.system()})"}


def _run_osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], check=False,
                           capture_output=True, text=True, timeout=_TIMEOUT_S)


def _spotify_running() -> bool:
    try:
        out = _run_osascript(
            'tell application "System Events" to (name of processes) contains "Spotify"'
        )
    except Exception:  # noqa: BLE001 — treat any probe failure as "not running"
        return False
    return out.returncode == 0 and out.stdout.strip().lower() == "true"


def _target_app() -> str:
    return "Spotify" if _spotify_running() else "Music"


def media_control(action: str) -> dict[str, Any]:
    """Run a playback transport action against Spotify (if running)
    else Music.app: play / pause / next / skip / previous."""
    action_clean = (action or "").strip().lower()
    if action_clean not in _TRANSPORT_ACTIONS:
        return {"ok": False,
                 "error": (f"unknown action {action_clean!r} — use one of "
                           f"{_TRANSPORT_ACTIONS} (for reading state, use now_playing)")}
    if platform.system() != "Darwin":
        return {"ok": False, **_not_macos_error()}
    if shutil.which("osascript") is None:
        return {"ok": False, "error": "osascript not on PATH (macOS-only utility)"}

    app = _target_app()
    verb = _ACTION_VERB[action_clean]
    script = f'tell application "{app}" to {verb}'
    try:
        out = _run_osascript(script)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"ok": False, "error": (out.stderr or "osascript failed").strip()}
    return {"ok": True, "app": app, "action": action_clean}


def now_playing() -> dict[str, Any]:
    """Read the current track + player state from Spotify (if running)
    else Music.app, without changing anything."""
    if platform.system() != "Darwin":
        return {"ok": False, **_not_macos_error()}
    if shutil.which("osascript") is None:
        return {"ok": False, "error": "osascript not on PATH (macOS-only utility)"}

    app = _target_app()
    script = (
        f'tell application "{app}" to if player state is playing or '
        f'player state is paused then return (name of current track) & " — " & '
        f'(artist of current track) & " (" & (player state as string) & ")"'
    )
    try:
        out = _run_osascript(script)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"ok": False, "error": (out.stderr or "osascript failed").strip()}
    text = out.stdout.strip()
    if not text:
        return {"ok": True, "app": app, "playing": False, "now_playing": None}
    return {"ok": True, "app": app, "playing": True, "now_playing": text}


# ── Agent-facing tool wrappers ────────────────────────────────────────


@register_tool_from_function(name="media_control")
@requires_tier(PermissionTier.EXTERNAL_EFFECT, skill="media_control",
               operation="media_control", summary="control music playback")
def _t_media_control(action: str) -> dict:
    """Control music playback transport — "play"/"pause"/"next" (or
    "skip")/"previous". Targets Spotify if it's running, else Music.app
    (launched on demand). To READ what's playing without any
    confirmation, use now_playing() instead — this tool is for actions
    that actually change playback. Returns {ok: True, app, action} or
    {ok: False, error}."""
    return media_control(action=action)


@register_tool_from_function(name="now_playing", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="media_control", operation="now_playing",
               summary="read the current track")
def _t_now_playing() -> dict:
    """What's playing right now — "what song is this", "is music
    playing". Reads Spotify (if running) else Music.app; changes
    nothing. Returns {ok: True, playing, now_playing} or {ok: False,
    error}."""
    return now_playing()


__all__ = ["media_control", "now_playing"]
