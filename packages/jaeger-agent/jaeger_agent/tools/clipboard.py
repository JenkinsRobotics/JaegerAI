"""Clipboard — ``clipboard_read`` / ``clipboard_write`` over
``pbpaste`` / ``pbcopy``. Read is READ_ONLY; write is WRITE_LOCAL (it
overwrites whatever the user had on their clipboard — a local-only
change, not an external effect, but not free either)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_os.core.safety.permissions import PermissionTier, requires_tier

_TIMEOUT_S = 5


def _not_macos_error() -> dict[str, Any]:
    return {"error": f"clipboard tools are only available on macOS (got {platform.system()})"}


def clipboard_read() -> dict[str, Any]:
    """Read the current text on the system clipboard via ``pbpaste``."""
    if platform.system() != "Darwin":
        return {"read": False, **_not_macos_error()}
    if shutil.which("pbpaste") is None:
        return {"read": False, "error": "pbpaste not on PATH (macOS-only utility)"}
    try:
        out = subprocess.run(["pbpaste"], check=False, capture_output=True,
                              text=True, timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return {"read": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"read": False, "error": (out.stderr or "pbpaste failed").strip()}
    return {"read": True, "text": out.stdout}


def clipboard_write(text: str) -> dict[str, Any]:
    """Replace the system clipboard's contents via ``pbcopy``."""
    if platform.system() != "Darwin":
        return {"written": False, **_not_macos_error()}
    if shutil.which("pbcopy") is None:
        return {"written": False, "error": "pbcopy not on PATH (macOS-only utility)"}
    try:
        out = subprocess.run(["pbcopy"], check=False, input=text or "",
                              capture_output=True, text=True, timeout=_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return {"written": False, "error": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"written": False, "error": (out.stderr or "pbcopy failed").strip()}
    return {"written": True, "bytes": len((text or "").encode("utf-8"))}


# ── Agent-facing tool wrappers ────────────────────────────────────────


@register_tool_from_function(name="clipboard_read", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="clipboard", operation="clipboard_read",
               summary="read the system clipboard")
def _t_clipboard_read() -> dict:
    """Read the text currently on the system clipboard — "what's on my
    clipboard", or as a source for something the user just copied.
    Returns {read: True, text} or {read: False, error}."""
    return clipboard_read()


@register_tool_from_function(name="clipboard_write")
@requires_tier(PermissionTier.WRITE_LOCAL, skill="clipboard", operation="clipboard_write",
               summary="write to the system clipboard")
def _t_clipboard_write(text: str) -> dict:
    """Put text on the system clipboard — "copy this", "put X on my
    clipboard". Overwrites whatever was there. Returns {written: True,
    bytes} or {written: False, error}."""
    return clipboard_write(text=text)


__all__ = ["clipboard_read", "clipboard_write"]
