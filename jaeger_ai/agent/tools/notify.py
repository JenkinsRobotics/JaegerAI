"""Notify — one tool, ``notify``, over ``osascript ... display
notification``. WRITE_LOCAL: it puts something visible on the user's
screen (a local UI effect, not an external side effect reaching outside
the machine)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 5


def _escape_applescript(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str) -> dict[str, Any]:
    """Show a macOS notification banner via Notification Center."""
    title_clean = (title or "").strip()
    message_clean = (message or "").strip()
    if not title_clean and not message_clean:
        return {"shown": False, "error": "title and message are both empty"}
    if platform.system() != "Darwin":
        return {"shown": False,
                 "error": f"notify is only available on macOS (got {platform.system()})"}
    if shutil.which("osascript") is None:
        return {"shown": False, "error": "osascript not on PATH (macOS-only utility)"}

    script = (
        f'display notification "{_escape_applescript(message_clean)}" '
        f'with title "{_escape_applescript(title_clean)}"'
    )
    try:
        out = subprocess.run(["osascript", "-e", script], check=False,
                              capture_output=True, text=True, timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return {"shown": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"shown": False, "error": (out.stderr or "osascript failed").strip()}
    return {"shown": True, "title": title_clean, "message": message_clean}


# ── Agent-facing tool wrapper ────────────────────────────────────────


@register_tool_from_function(name="notify")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="notify", operation="notify",
               summary="show a macOS notification banner")
def _t_notify(title: str, message: str) -> dict:
    """Show a notification banner on this Mac's screen — "notify me
    when...", "pop up a reminder saying X". Not a message to another
    person (use send_message/send_email for that) — this is local,
    on-screen only. Returns {shown: True, title, message} or
    {shown: False, error}."""
    return notify(title=title, message=message)


__all__ = ["notify"]
