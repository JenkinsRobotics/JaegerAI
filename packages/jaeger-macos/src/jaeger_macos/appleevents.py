"""Cross-process AppleEvents serializer & bounded osascript execution.

macOS GUI apps (Mail.app, Calendar.app, Contacts.app, Messages.app, System Events)
handle AppleEvents on a single main queue. Concurrent osascript calls from
parallel threads OR separate processes (Gateway, skills, helper scripts) contend
and time out simultaneously.

``appleevents_lock`` enforces BOTH a process-local ``threading.RLock`` AND an
interprocess ``fcntl.flock`` lockfile so separate processes serialize cleanly.
"""

from __future__ import annotations

import contextlib
import os
import platform
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover — non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_SAFE_TARGET = re.compile(r"[^a-z0-9_-]+")


def _lock_dir() -> Path:
    override = os.environ.get("JAEGER_APPLEEVENTS_LOCK_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    state_root = os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME")
    if state_root:
        return Path(state_root).expanduser() / "run"
    return Path.home() / ".jaeger" / "run"


def _thread_lock_for(key: str) -> threading.RLock:
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def appleevents_lock(target: str = "global") -> Iterator[None]:
    """Serialize AppleEvents across threads AND processes for ``target``."""
    slug = _SAFE_TARGET.sub("-", (target or "global").strip().lower()).strip("-") or "global"
    lock_file = _lock_dir() / f"appleevents-{slug}.lock"
    tlock = _thread_lock_for(str(lock_file))
    with tlock:
        fd: int | None = None
        try:
            lock_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            # Read-only or restricted temp environment: retain in-process thread lock.
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                fd = None
        try:
            yield
        finally:
            if fd is not None:
                try:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)


def escape_applescript(text: str) -> str:
    """Escape backslashes and double-quotes for an AppleScript string literal."""
    return (text or "").replace("\\", "\\\\").replace('"', '\\"')


def run_applescript(
    script: str,
    *,
    timeout_seconds: float = 25.0,
    target: str = "global",
    argv: list[str] | None = None,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run one bounded, cross-process-serialized ``osascript`` call. Never raises."""
    if platform.system() != "Darwin":
        return {
            "ok": False,
            "success": False,
            "exit_code": 1,
            "timed_out": False,
            "raw_output": "",
            "moved_count": 0,
            "error": "AppleScript is only available on macOS",
        }
    if shutil.which("osascript") is None:
        return {
            "ok": False,
            "success": False,
            "exit_code": 1,
            "timed_out": False,
            "raw_output": "",
            "moved_count": 0,
            "error": "osascript not on PATH (macOS-only utility)",
        }
    cmd = ["osascript", "-e", script]
    if argv:
        cmd.extend(argv)
    exec_fn = runner or subprocess.run
    try:
        with appleevents_lock(target):
            out = exec_fn(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "success": False,
            "exit_code": 124,
            "timed_out": True,
            "raw_output": "",
            "moved_count": 0,
            "error": (
                f"AppleScript timed out after {timeout_seconds}s. Do not repeat "
                "without narrowing the query (smaller batch, named account)."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "success": False,
            "exit_code": 1,
            "timed_out": False,
            "raw_output": "",
            "moved_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }
    raw = (getattr(out, "stdout", "") or "").strip()
    rc = int(getattr(out, "returncode", 1))
    if rc != 0:
        err = (getattr(out, "stderr", "") or getattr(out, "stdout", "") or "osascript failed").strip()
        return {
            "ok": False,
            "success": False,
            "exit_code": rc,
            "timed_out": False,
            "raw_output": raw,
            "moved_count": 0,
            "error": err,
        }
    return {
        "ok": True,
        "success": True,
        "exit_code": 0,
        "timed_out": False,
        "raw_output": raw,
        "moved_count": 0,
        "error": None,
    }
