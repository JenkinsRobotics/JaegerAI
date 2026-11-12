"""Process liveness — the one ``pid_alive`` every layer uses.

There were ten private copies of this probe across the app, the agent
framework and the OS package, with slightly different answers for
``pid <= 0`` and ``EPERM``. This is the single definition.
"""
from __future__ import annotations

import os

__all__ = ["pid_alive"]


def pid_alive(pid: int) -> bool:
    """True when ``pid`` names a live process on this host.

    ``os.kill(pid, 0)`` is a no-op signal that raises if the process is
    gone. ``EPERM`` means it exists but belongs to another user, which
    still counts as alive. Non-positive pids are never alive (``0`` and
    negatives would address process groups).
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
