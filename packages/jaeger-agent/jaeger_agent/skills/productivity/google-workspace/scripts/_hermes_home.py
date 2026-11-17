"""Resolve Jaeger's state folder for standalone skill scripts.

Skill scripts may run outside the Jaeger process (system Python, CI), so
this module uses only the stdlib. The function names keep their upstream
(Hermes) spelling so the vendored google-workspace scripts import them
unchanged. It never reads ~/.hermes.

All scripts under ``google-workspace/scripts/`` import from here instead
of reading the state folder from the environment themselves.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_hermes_home() -> Path:
    """Return Jaeger state (legacy name). Never reads ~/.hermes."""
    for key in ("JAEGER_WEBUI_AGENT_STATE", "JAEGER_STATE_DIR", "JAEGER_STATE_HOME", "JAEGER_HOME"):
        val = os.environ.get(key, "").strip()
        if val:
            return Path(val).expanduser()
    return Path.home() / ".jaeger"


def display_hermes_home() -> str:
    """Return a user-friendly ``~/``-shortened display string."""
    home = get_hermes_home()
    try:
        return "~/" + str(home.relative_to(Path.home()))
    except ValueError:
        return str(home)
