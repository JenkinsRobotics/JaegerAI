"""Local Unix socket so more than one first-party UI can share one brain.

Stdio is 1:1. The instance lock is 1:1. Together they made ARES and
JaegerAI.app fight. This socket is the attach point: the process that
holds the lock listens here, and every other client connects instead of
spawning a second ``jaeger bridge``.

Auth is the filesystem: the socket is ``0600`` under the instance dir.
Loopback only — AF_UNIX, no TCP.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

SOCKET_NAME = "bridge.sock"


def socket_path(layout: Any) -> Path | None:
    root = getattr(layout, "root", None)
    if root is None:
        return None
    return Path(str(root)) / "run" / SOCKET_NAME


def candidate_paths(*, home: str | os.PathLike[str] | None,
                    instance: str | None) -> list[Path]:
    """Where a foreign client (ARES) should look, without importing Jaeger."""
    name = (instance or "default").strip() or "default"
    out: list[Path] = []
    env_dir = os.environ.get("JAEGER_INSTANCE_DIR", "").strip()
    if env_dir:
        out.append(Path(env_dir).expanduser() / "run" / SOCKET_NAME)
    if home:
        root = Path(str(home)).expanduser()
        out.append(root / ".jaeger_ai" / "instances" / name / "run" / SOCKET_NAME)
    out.append(Path.home() / ".jaeger" / "instances" / name / "run" / SOCKET_NAME)
    # unique, keep order
    seen: set[str] = set()
    unique: list[Path] = []
    for path in out:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_live_socket(*, home: str | os.PathLike[str] | None = None,
                     instance: str | None = None) -> Path | None:
    """Return the first candidate that accepts a connection."""
    for path in candidate_paths(home=home, instance=instance):
        if not path.exists():
            continue
        sock = try_connect(path, timeout_s=0.4)
        if sock is not None:
            close_quietly(sock)
            return path
    return None


def bind(path: Path) -> socket.socket:
    """Listen on ``path``. Replaces a stale socket file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(str(path))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    sock.listen(8)
    sock.settimeout(1.0)
    return sock


def try_connect(path: Path, *, timeout_s: float = 2.0) -> socket.socket | None:
    """Connect to a live socket, or None if nothing is listening."""
    if not path.exists():
        return None
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect(str(path))
    except OSError:
        sock.close()
        return None
    sock.settimeout(None)
    return sock


def close_quietly(sock: socket.socket | None) -> None:
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


__all__ = [
    "SOCKET_NAME",
    "bind",
    "candidate_paths",
    "close_quietly",
    "find_live_socket",
    "socket_path",
    "try_connect",
]
