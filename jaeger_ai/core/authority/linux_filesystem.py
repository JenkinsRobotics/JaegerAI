"""Validate the existing empty-root execute_code sandbox on Linux.

This is deliberately not an arbitrary shell sandbox. Unknown Bubblewrap
options fail closed: the proof depends on an empty root, explicit mounts and
the final read-only root. Keep this grammar aligned with the producer in
``jaeger_agent.tools.code._sandboxed_python_command``.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
from typing import Protocol, Sequence


class PathRestriction(Protocol):
    path: Path
    deny_read: bool


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def confine_existing_bwrap(
    command: Sequence[str], restrictions: Sequence[PathRestriction],
) -> list[str]:
    """Return a proven isolated execute_code argv, or refuse before spawning.

    Checking both sides of each mount prevents aliases from importing a
    protected host store or mapping a writable directory over a protected
    namespace location. Unmapped paths are absent, including future files;
    the final read-only root prevents creating their unmapped parents.
    """
    argv = list(command)

    def reject(detail: str) -> None:
        raise PermissionError(f"Linux filesystem authority: {detail}")

    bwrap = shutil.which("bwrap")
    if not argv or not bwrap or Path(argv[0]).resolve() != Path(bwrap).resolve():
        reject("only the existing isolated execute_code Bubblewrap sandbox is supported")
    if not Path(bwrap).is_file():
        reject("Bubblewrap executable is unavailable")

    required = {"--die-with-parent", "--new-session", "--unshare-user",
                "--unshare-net", "--unshare-ipc"}
    seen: set[str] = set()
    frozen = False
    chdir_seen = False
    mounted = False

    def absolute(value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            reject("sandbox paths must be absolute")
        return Path(os.path.normpath(value))

    def check_mount(value: str, *, writable: bool) -> None:
        path = absolute(value)
        for restriction in restrictions:
            if not writable and not restriction.deny_read:
                continue
            for candidate in (path, path.resolve()):
                if _overlap(candidate, restriction.path.resolve()):
                    reject(f"mount overlaps protected resource {restriction.path}")

    index = 1
    while index < len(argv) and argv[index].startswith("--"):
        option = argv[index]
        if option in required:
            if option in seen or mounted or frozen:
                reject("unsupported namespace option order")
            seen.add(option)
            index += 1
            continue
        arity = {"--ro-bind": 2, "--bind": 2, "--symlink": 2,
                 "--dev": 1, "--remount-ro": 1, "--chdir": 1}.get(option)
        if arity is None or index + arity >= len(argv):
            reject("unsupported or incomplete Bubblewrap option")
        values = argv[index + 1:index + 1 + arity]
        if seen != required:
            reject("required namespace isolation is missing")
        if option in {"--bind", "--ro-bind"}:
            if frozen:
                reject("mount appears after root was frozen")
            for value in values:
                if absolute(value).resolve() == Path("/"):
                    reject("binding the host root is forbidden")
                check_mount(value, writable=option == "--bind")
            mounted = True
        elif option == "--symlink":
            destination = absolute(values[1])
            # The producer recreates host merged-/usr links in the empty
            # root. Never create links inside a bind mount or invent aliases.
            if (frozen or len(destination.parts) != 2
                    or not destination.is_symlink()
                    or os.readlink(destination) != values[0]):
                reject("unsupported sandbox symlink")
            check_mount(values[1], writable=False)
        elif option == "--dev":
            if frozen or values != ["/dev"]:
                reject("only the private /dev mount is supported")
            check_mount(values[0], writable=True)
            mounted = True
        elif option == "--remount-ro":
            if frozen or values != ["/"]:
                reject("root must be frozen exactly once")
            frozen = True
        elif option == "--chdir":
            if not frozen or chdir_seen:
                reject("unsupported working-directory option")
            absolute(values[0])
            chdir_seen = True
        index += 1 + arity

    tail = argv[index:]
    if (seen != required or not frozen or not mounted or not chdir_seen
            or len(tail) != 5 or tail[1:4] != ["-I", "-B", "-c"]
            or Path(tail[0]).resolve() != Path(sys.executable).resolve()):
        reject("expected the isolated execute_code interpreter command")
    return argv
