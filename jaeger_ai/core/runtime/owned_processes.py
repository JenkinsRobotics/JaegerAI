"""Process trees Jaeger can prove it owns.

Automatic shutdown may signal these PIDs. It must not select processes by
name: a command line containing ``jaeger`` is not proof of ownership.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def process_alive(pid: int) -> bool:
    if pid <= 1 or pid == os.getpid():
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


def _children_by_parent() -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat = (entry / "stat").read_bytes()
            except OSError:
                continue
            end = stat.rfind(b")")
            if end < 0:
                continue
            fields = stat[end + 2 :].split()
            if len(fields) < 2:
                continue
            try:
                children.setdefault(int(fields[1]), []).append(int(entry.name))
            except ValueError:
                continue
        return children
    try:
        completed = subprocess.run(
            ["ps", "-ax", "-o", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return children
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        children.setdefault(int(parts[1]), []).append(int(parts[0]))
    return children


def descendants_of(pid: int) -> set[int]:
    """Children of ``pid``, including grandchildren. Not a name search."""
    if pid <= 1:
        return set()
    children = _children_by_parent()
    found: set[int] = set()
    stack = list(children.get(pid, ()))
    while stack:
        current = stack.pop()
        if current in found or current <= 1 or current == os.getpid():
            continue
        found.add(current)
        stack.extend(children.get(current, ()))
    return found


def snapshot_owned(root_pids: set[int] | list[int]) -> set[int]:
    """The roots plus the descendants that exist at this moment."""
    owned: set[int] = set()
    for pid in root_pids:
        if process_alive(pid):
            owned.add(pid)
            owned |= descendants_of(pid)
    return owned


def survivors(pids: set[int] | list[int]) -> list[int]:
    return sorted(pid for pid in pids if process_alive(pid))
