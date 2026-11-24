"""Pure macOS TCC permission diagnostics & prompt helpers."""

from __future__ import annotations

import sys
from typing import Callable

from .appleevents import run_applescript


def probe_tcc_status(*, fda_probe: Callable[[], bool | None] | None = None) -> dict[str, bool | None]:
    """Read-only TCC grant state; ``None`` = undeterminable. Never prompts."""
    if sys.platform != "darwin":
        return {}
    out: dict[str, bool | None] = {}
    try:
        import ApplicationServices as _AX
        out["accessibility"] = bool(_AX.AXIsProcessTrusted())
    except Exception:  # noqa: BLE001 — PyObjC missing
        out["accessibility"] = None
    try:
        import Quartz
        out["screen_recording"] = bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001
        out["screen_recording"] = None
    if fda_probe is not None:
        try:
            out["full_disk_access"] = fda_probe()
        except Exception:  # noqa: BLE001
            out["full_disk_access"] = None
    return out


def request_tcc_permissions(
    *,
    automation_targets: tuple[str, ...] = ("System Events", "Finder"),
    fda_probe: Callable[[], bool | None] | None = None,
) -> dict[str, bool | None]:
    """Trigger OS TCC prompts once, then return :func:`probe_tcc_status`."""
    if sys.platform != "darwin":
        return {}
    try:
        import ApplicationServices as _AX
        _AX.AXIsProcessTrustedWithOptions({_AX.kAXTrustedCheckOptionPrompt: True})
    except Exception:  # noqa: BLE001
        pass
    try:
        import Quartz
        Quartz.CGRequestScreenCaptureAccess()
    except Exception:  # noqa: BLE001
        pass
    for target in automation_targets:
        run_applescript(
            f'tell application "{target}" to count windows',
            timeout_seconds=15.0,
            target="tcc",
        )
    return probe_tcc_status(fda_probe=fda_probe)
