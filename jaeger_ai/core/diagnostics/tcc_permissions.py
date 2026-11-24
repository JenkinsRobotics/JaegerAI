"""macOS TCC permission preflight — ask for everything up front.

Apple does not let ANY installer grant privacy (TCC) permissions
programmatically — Accessibility, Screen Recording, Automation, and
Full Disk Access can only be granted by the user. What we CAN do is
trigger every prompt at first app boot instead of letting individual
tools fail mid-task, and report exact grant state in ``jaeger doctor``.

The catch that makes permissions look "inconsistent": a TCC grant
attaches to the HOST APP identity (JaegerAI.app vs Terminal vs an IDE),
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
    from jaeger_macos.tcc import probe_tcc_status
    from jaeger_ai.core.diagnostics.doctor import _probe_fda
    return probe_tcc_status(fda_probe=_probe_fda)


def request_all() -> dict[str, bool | None]:
    """Trigger every TCC prompt the OS allows, then return :func:`status`.

    Safe to call repeatedly — already-granted (or already-denied)
    permissions never re-prompt; macOS only prompts on "undetermined".
    """
    if sys.platform != "darwin":
        return {}
    from jaeger_macos.tcc import request_tcc_permissions
    from jaeger_ai.core.diagnostics.doctor import _probe_fda
    return request_tcc_permissions(fda_probe=_probe_fda)


def first_boot_preflight() -> None:
    """Progressive authorization: do not prompt for every TCC grant at boot.

    Commissioning requests only the permissions required for the chosen
    interaction mode and approved capabilities. ``request_all`` remains
    available for Advanced Setup and ``jaeger doctor``.
    """
    return
