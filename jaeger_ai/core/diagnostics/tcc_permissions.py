"""macOS TCC permission preflight — ask for everything up front.

Apple does not let ANY installer grant privacy (TCC) permissions
programmatically — Accessibility, Screen Recording, Automation, and
Full Disk Access can only be granted by the user. What we CAN do is
trigger every prompt at first app boot instead of letting individual
tools fail mid-task, and report exact grant state in ``jaeger doctor``.

The catch that makes permissions look "inconsistent": a TCC grant
attaches to the HOST APP identity (JaegerOS.app vs Terminal vs an IDE),
so the same tool works from one launch path and fails from another.
That's why :func:`request_all` must run inside the agent's own process
(the bridge), not in install.sh — the prompt then names, and the grant
then covers, the app the agent actually runs as. Child processes the
agent spawns inherit that grant (macOS attributes them to the
"responsible" app), so one grant covers all downstream tools.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_MARKER = Path.home() / ".jaeger" / "tcc_preflight_done"


def status() -> dict[str, bool | None]:
    """Read-only grant state; ``None`` = undeterminable. Never prompts."""
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
    from jaeger_ai.core.diagnostics.doctor import _probe_fda
    out["full_disk_access"] = _probe_fda()
    # Automation is per-target-app and has no read API worth trusting;
    # request_all() triggers its prompts instead.
    return out


def request_all() -> dict[str, bool | None]:
    """Trigger every TCC prompt the OS allows, then return :func:`status`.

    Safe to call repeatedly — already-granted (or already-denied)
    permissions never re-prompt; macOS only prompts on "undetermined".
    """
    if sys.platform != "darwin":
        return {}
    try:
        import ApplicationServices as _AX
        _AX.AXIsProcessTrustedWithOptions(
            {_AX.kAXTrustedCheckOptionPrompt: True})
    except Exception:  # noqa: BLE001
        pass
    try:
        import Quartz
        Quartz.CGRequestScreenCaptureAccess()
    except Exception:  # noqa: BLE001
        pass
    # Automation: one benign Apple event per common target raises that
    # target's one-time "wants to control" prompt now, not mid-task.
    for target in ("System Events", "Finder"):
        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{target}" to count windows'],
                capture_output=True, timeout=15,
            )
        except Exception:  # noqa: BLE001
            pass
    return status()


def first_boot_preflight() -> None:
    """Run :func:`request_all` once per machine (marker-file guarded).

    Called from the bridge boot path so the prompts carry the app's own
    identity. Never raises; never blocks boot on a slow prompt (the OS
    dialogs are asynchronous — the calls return immediately).
    """
    if sys.platform != "darwin" or _MARKER.exists():
        return
    try:
        _MARKER.parent.mkdir(parents=True, exist_ok=True)
        request_all()
        _MARKER.write_text("v1\n")
    except Exception:  # noqa: BLE001 — best-effort, boot must proceed
        pass
