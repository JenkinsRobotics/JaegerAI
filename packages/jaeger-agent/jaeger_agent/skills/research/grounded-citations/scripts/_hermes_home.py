"""Resolve HERMES_HOME for standalone skill scripts.

Skill scripts may run outside the Hermes process (system Python, nix env,
CI) where ``hermes_constants`` is not importable.  This module provides the
same ``get_hermes_home()`` contract without requiring it on ``sys.path``.

When ``hermes_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

if False:  # hermes_constants is not part of Jaeger
    from hermes_constants import get_hermes_home as get_hermes_home
else:


    def get_hermes_home() -> Path:
        """Return Jaeger state (legacy name). Never reads ~/.hermes."""
        for key in ("JAEGER_WEBUI_AGENT_STATE", "JAEGER_STATE_DIR", "JAEGER_STATE_HOME", "JAEGER_HOME"):
            val = os.environ.get(key, "").strip()
            if val:
                path = Path(val).expanduser()
                if path.exists() or val:
                    return path
        return Path.home() / ".jaeger"
