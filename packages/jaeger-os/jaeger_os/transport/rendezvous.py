"""Finding a running app's bus, on THIS machine.

    /tmp/jaeger/<app>.bus.json   {"xsub": "tcp://…", "xpub": "tcp://…"}

A subprocess node is told where the bus is by its parent, through
``JAEGER_TRANSPORT_XSUB``/``XPUB``. Anything the app did NOT spawn —
a monitor, a recorder, a second terminal — had no way to find it at
all. The control plane already solved this for its own socket by
putting it at a well-known path; this is the same trick for the bus.

DELIBERATELY LOCAL ONLY. No multicast, no beacon, nothing listening on
a network interface. Discovering a bus across machines is a different
feature with a different threat model — it means opening the bus to
whoever can reach the port, and the bus carries motor commands. When
that is genuinely needed, ZeroMQ's own Zyre already does the beacon
part properly and hand-rolling it would be the wrong call.

The directory's ``0700`` mode IS the access control, exactly as for
the control socket: anything that can read this file can publish to
the bus.
"""

from __future__ import annotations

import json
import os
import pathlib

#: Same directory the control plane uses, for the same reason: one
#: place an operator can look to see what is running.
from jaeger_os.app.control import DEFAULT_SOCKET_DIR


def rendezvous_path(app_name: str = "jaeger") -> pathlib.Path:
    return DEFAULT_SOCKET_DIR / f"{app_name}.bus.json"


def publish(app_name: str, *, xsub: str, xpub: str) -> pathlib.Path:
    """Record where this app's bus is. Called by the app at boot.

    Written to a temporary file and renamed, so a reader never sees a
    half-written document — a torn read here would hand someone a
    truncated endpoint and a connection that silently goes nowhere.
    """
    DEFAULT_SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DEFAULT_SOCKET_DIR.chmod(0o700)
    except OSError:
        pass

    path = rendezvous_path(app_name)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"app": app_name, "pid": os.getpid(), "xsub": xsub, "xpub": xpub},
        indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def find(app_name: str = "jaeger") -> dict | None:
    """Where ``app_name``'s bus is, or ``None`` if it is not running.

    A stale file from a crashed run is treated as absent: the pid is
    checked, and a record whose process is gone is removed rather than
    handed back. Otherwise a crash leaves every future connect
    attempting a port nobody is bound to, which fails as silence.
    """
    path = rendezvous_path(app_name)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    pid = record.get("pid")
    if isinstance(pid, int) and not _alive(pid):
        withdraw(app_name)
        return None
    if not record.get("xsub") or not record.get("xpub"):
        return None
    return record


def withdraw(app_name: str = "jaeger") -> None:
    """Remove the record. Called on shutdown; idempotent."""
    try:
        rendezvous_path(app_name).unlink()
    except OSError:
        pass


def running() -> list[dict]:
    """Every app advertising a bus on this machine, stale ones pruned."""
    if not DEFAULT_SOCKET_DIR.is_dir():
        return []
    out = []
    for path in sorted(DEFAULT_SOCKET_DIR.glob("*.bus.json")):
        record = find(path.name[: -len(".bus.json")])
        if record:
            out.append(record)
    return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # exists, owned by someone else
    except OSError:
        return True          # be conservative: do not prune on doubt
    return True


__all__ = ["rendezvous_path", "publish", "find", "withdraw", "running"]
