"""Live screen context — capture the display, then OCR it.

``ocr_file`` already reads a path. Long-running "what's on my screen"
turns were missing the capture half: the model had to ask the operator
to screenshot first. This module is that half.

Two tools, same capture+OCR path:

  * ``see_screen`` — main display (default) or the frontmost window
  * ``ocr_window`` — alias that forces the frontmost window

Requires macOS Screen Recording (TCC). Capture failures return a
grant-reminder instead of raising. OCR failures still return the
screenshot path so a later ``ocr_file`` can retry.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jaeger_os.core.safety.permissions import PermissionTier, requires_tier
from jaeger_os.core.tools.tool_registry import register_tool_from_function


def _capture_path() -> Path:
    try:
        from jaeger_ai.main import _pipeline

        layout = _pipeline.get("layout")
        run_dir = getattr(layout, "run_dir", None)
        if run_dir is not None:
            path = Path(str(run_dir))
            path.mkdir(parents=True, exist_ok=True)
            return path / "screen_latest.png"
    except Exception:  # noqa: BLE001
        pass
    return Path(tempfile.gettempdir()) / "jaeger_screen_latest.png"


def _screen_recording_granted() -> bool | None:
    """True / False when Quartz can say; None when it cannot."""
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz

        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001
        return None


def _frontmost_window_id() -> int | None:
    """CGWindowID of the frontmost on-screen layer-0 window, or None."""
    if platform.system() != "Darwin":
        return None
    try:
        import Quartz
    except Exception:  # noqa: BLE001
        return None
    try:
        opts = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        info = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
    except Exception:  # noqa: BLE001
        return None
    for item in info or []:
        if not isinstance(item, dict):
            continue
        layer = item.get("kCGWindowLayer", 1)
        bounds = item.get("kCGWindowBounds") or {}
        width = float(bounds.get("Width") or 0)
        height = float(bounds.get("Height") or 0)
        if int(layer or 1) != 0 or width < 64 or height < 64:
            continue
        number = item.get("kCGWindowNumber")
        if number:
            return int(number)
    return None


def _run_screencapture(dest: Path, *, window_id: int | None = None) -> dict[str, Any]:
    binary = shutil.which("screencapture")
    if not binary:
        return {"ok": False, "error": "screencapture is not on PATH"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [binary, "-x"]
    if window_id is not None:
        cmd.extend(["-l", str(window_id)])
    else:
        cmd.append("-m")
    cmd.append(str(dest))
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=20, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "screencapture timed out"}
    except OSError as exc:
        return {"ok": False, "error": f"screencapture failed: {exc}"}
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        granted = _screen_recording_granted()
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        if granted is False:
            return {
                "ok": False,
                "error": (
                    "Screen Recording is not granted. Enable it for this "
                    "app in System Settings ▸ Privacy & Security ▸ "
                    "Screen Recording, then retry see_screen."
                ),
                "tcc": "screen_recording",
            }
        detail = stderr or f"exit {proc.returncode}"
        return {"ok": False, "error": f"screencapture failed: {detail}"}
    return {"ok": True, "path": str(dest)}


def capture_screen(target: str = "screen") -> dict[str, Any]:
    """Take a screenshot. ``target`` is ``screen`` (main display) or
    ``window`` (frontmost). Does not OCR."""
    if platform.system() != "Darwin":
        return {
            "ok": False,
            "error": f"see_screen is only available on macOS (got {platform.system()})",
        }
    kind = (target or "screen").strip().lower()
    if kind in {"display", "full", "desktop", ""}:
        kind = "screen"
    if kind not in {"screen", "window"}:
        return {
            "ok": False,
            "error": f"unknown target {target!r}; use screen or window",
        }
    dest = _capture_path()
    window_id = _frontmost_window_id() if kind == "window" else None
    note = ""
    if kind == "window" and window_id is None:
        note = "frontmost window id unavailable — captured the main display"
        kind = "screen"
    captured = _run_screencapture(dest, window_id=window_id)
    if not captured.get("ok"):
        return captured
    payload = {
        "ok": True,
        "path": captured["path"],
        "target": kind,
        "bytes": dest.stat().st_size,
    }
    if window_id is not None:
        payload["window_id"] = window_id
    if note:
        payload["note"] = note
    return payload


def see_screen(target: str = "screen") -> dict[str, Any]:
    """Capture the live display and OCR it. Returns the screenshot
    path plus extracted text."""
    captured = capture_screen(target=target)
    if not captured.get("ok"):
        return captured
    path = str(captured.get("path") or "")
    ocr_result: dict[str, Any] = {}
    try:
        from jaeger_agent.tools.ocr import ocr_file

        ocr_result = ocr_file(path) if path else {"ok": False, "error": "no path"}
    except Exception as exc:  # noqa: BLE001
        ocr_result = {
            "ok": False,
            "error": f"OCR failed: {type(exc).__name__}: {exc}",
        }
    text = str(ocr_result.get("text") or "")
    payload = {
        "ok": True,
        "captured": True,
        "path": path,
        "target": captured.get("target") or target,
        "text": text,
        "page_count": ocr_result.get("page_count") or (1 if text else 0),
        "ocr_ok": bool(ocr_result.get("ok")),
    }
    if captured.get("note"):
        payload["note"] = captured["note"]
    if captured.get("window_id") is not None:
        payload["window_id"] = captured["window_id"]
    if not ocr_result.get("ok"):
        payload["ocr_error"] = str(ocr_result.get("error") or "OCR unavailable")
        if ocr_result.get("available") is False:
            payload["ocr_available"] = False
    return payload


@register_tool_from_function(name="see_screen", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="screen", operation="see_screen",
               summary="capture the live display and OCR it")
def _t_see_screen(target: str = "screen") -> dict:
    """Look at the operator's screen right now. Captures the main
    display (default) or the frontmost window (``target="window"``)
    and returns the on-screen text via OCR. Use this when the user
    says "what's on my screen", "look at this", or "read this window".
    Requires macOS Screen Recording permission. Returns {ok, text,
    path, target} — cite the text, don't guess."""
    return see_screen(target=target)


@register_tool_from_function(name="ocr_window", side_effect="read")
@requires_tier(PermissionTier.READ_ONLY, skill="screen", operation="ocr_window",
               summary="capture the frontmost window and OCR it")
def _t_ocr_window() -> dict:
    """OCR the frontmost on-screen window. Same capture+OCR path as
    see_screen(target="window"). Use when the user wants the active
    window rather than the whole display."""
    return see_screen(target="window")


__all__ = [
    "capture_screen",
    "see_screen",
]
