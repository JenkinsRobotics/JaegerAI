"""Single resident EntityRuntime owner for a state root.

Gateway and the daemon compete for an exclusive flock. CLI one-shots
attach to the same sqlite identity/event fabric regardless of who holds
the lock; only the lock holder starts heartbeat, sleep-time, and sensors.
"""

from __future__ import annotations

import atexit
import logging
import os
from pathlib import Path

from jaeger_ai.core.instance.instance import operator_state_root

logger = logging.getLogger("jaeger.entity.resident")

LOCK_NAME = "entity.resident.lock"

_lock_fh = None
_is_resident = False


def lock_path(state_root: Path | None = None) -> Path:
    root = Path(state_root) if state_root else operator_state_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / LOCK_NAME


def is_resident() -> bool:
    return _is_resident


def try_become_resident(state_root: Path | None = None) -> bool:
    """Non-blocking exclusive lock. First process on this state root wins."""
    global _lock_fh, _is_resident
    if _is_resident:
        return True
    path = lock_path(state_root)
    try:
        fh = open(path, "a+", encoding="utf-8")
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        _lock_fh = fh
        _is_resident = True
        atexit.register(release_resident)
        logger.info("Acquired resident EntityRuntime lock at %s (pid %s)", path, os.getpid())
        return True
    except OSError:
        logger.info("Resident lock held by another process at %s", path)
        return False


def release_resident() -> None:
    global _lock_fh, _is_resident
    if _lock_fh is None:
        _is_resident = False
        return
    try:
        import fcntl
        fcntl.flock(_lock_fh.fileno(), fcntl.LOCK_UN)
        _lock_fh.close()
    except Exception:
        pass
    _lock_fh = None
    _is_resident = False
