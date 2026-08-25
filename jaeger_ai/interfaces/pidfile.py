"""PID-file lifecycle for the bridge process.

``jaeger status`` decides whether a bridge is running by reading
``jaeger.pid`` under the instance root (see
``jaeger_ai.cli.status_cmd._find_pid_file``). Nothing used to WRITE that
file, so status was structurally blind to a live bridge and its "stale pid
file" branch could never fire — field blocker #1.

Reclaim is deliberately conservative (blocker #4). PID numbers are
recycled, so "the PID is alive" is not "the PID is my predecessor": we
reclaim only when the recorded PID is dead, or is alive but demonstrably
not a bridge. A file owned by a live bridge is never stolen — startup
raises ``AlreadyRunning`` instead.

The on-disk format is one bare integer line, which is exactly what
``status_cmd`` already parses; keeping it that way means status needed no
change to start working.
"""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

__all__ = ["AlreadyRunning", "pid_path", "acquire", "read_owner"]

# The module argv marker that identifies a bridge process in `ps` output.
_BRIDGE_MARKER = "jaeger_ai.interfaces.bridge"


class AlreadyRunning(RuntimeError):
    """A live bridge already owns this instance's PID file."""

    def __init__(self, pid: int, path: Path) -> None:
        super().__init__(
            f"a bridge is already running for this instance (pid {pid}, {path})")
        self.pid = pid
        self.path = path


def pid_path(layout: Any) -> Path:
    """Where this instance's PID file lives.

    ``run/`` keeps process state out of the instance root proper;
    ``_find_pid_file`` checks both, so either location is discoverable.
    """
    return Path(layout.root) / "run" / "jaeger.pid"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just owned by another user.
        return True
    except OSError:
        return False
    return True


def _is_live_bridge(pid: int) -> bool:
    """True only if ``pid`` is alive AND looks like a bridge process.

    Guards against PID reuse: a recycled number belonging to some unrelated
    process must not make us refuse to start forever.
    """
    if not _pid_alive(pid):
        return False
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:  # noqa: BLE001 — ps unavailable/slow: fall back to liveness
        return True
    return _BRIDGE_MARKER in out


def read_owner(layout: Any) -> int | None:
    """The PID recorded for this instance, or None if absent/unreadable."""
    path = pid_path(layout)
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _write_atomic(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{pid}.tmp")
    tmp.write_text(f"{pid}\n")
    os.replace(tmp, path)          # atomic within the same directory


@contextmanager
def acquire(layout: Any) -> Iterator[Path]:
    """Claim this instance's PID file for the current process.

    Raises ``AlreadyRunning`` if a live bridge holds it. On exit the file is
    removed only if it still records OUR pid, so a successor that claimed
    the path in the meantime keeps its own registration.
    """
    path = pid_path(layout)
    existing = read_owner(layout)
    if existing is not None and existing != os.getpid():
        if _is_live_bridge(existing):
            raise AlreadyRunning(existing, path)
        # Dead, or alive but not a bridge (recycled PID) — safe to reclaim.

    mine = os.getpid()
    _write_atomic(path, mine)
    try:
        yield path
    finally:
        try:
            if path.read_text().strip() == str(mine):
                path.unlink()
        except (OSError, ValueError):
            pass       # already gone, or a successor rewrote it — leave it be
