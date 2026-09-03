"""Install the pinned Agentgateway binary into ~/.jaeger/bin."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import tempfile
import urllib.request
from pathlib import Path

from .constants import (
    RELEASE_URL,
    SHA256,
    VERSION,
    bin_dir,
    binary_link,
    binary_path,
    jaeger_home,
)


class InstallError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_copy(source: Path) -> Path | None:
    try:
        if source.is_file() and os.access(source, os.X_OK) and _sha256(source) == SHA256:
            return source
    except OSError:
        return None
    return None


def existing_verified_binary(root: Path | None = None) -> Path | None:
    """Return a local copy of v1.5.0 if one already verifies.

    Looks only at Jaeger-owned paths and the user-level ``~/.local/bin``
    command name. Does not search product-specific archive trees.
    """
    ordered = [
        binary_path(root),
        binary_link(root),
        Path.home() / ".local" / "bin" / "agentgateway",
    ]
    seen: set[str] = set()
    for candidate in ordered:
        try:
            resolved = candidate.resolve() if candidate.exists() else candidate
        except OSError:
            resolved = candidate
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        found = _verified_copy(resolved)
        if found is not None:
            return found
    return None


def _link_command(destination: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or not link.exists():
        link.unlink(missing_ok=True)
        link.symlink_to(destination)
        return
    if link.resolve() != destination:
        raise InstallError(f"Refusing to replace non-symlink command at {link}")


def install_binary(root: Path | None = None) -> Path:
    """Install agentgateway v1.5.0 under ~/.jaeger/bin and link ~/.local/bin."""
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise InstallError("This installer currently supports Apple Silicon macOS only.")

    destination = binary_path(root)
    jaeger_link = binary_link(root)
    user_link = Path.home() / ".local" / "bin" / "agentgateway"
    bin_dir(root).mkdir(parents=True, exist_ok=True)

    if destination.exists() and _sha256(destination) == SHA256:
        pass
    else:
        source = existing_verified_binary(root)
        if source is not None and source.resolve() != destination:
            shutil.copy2(source, destination)
            destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        else:
            with tempfile.NamedTemporaryFile(prefix="jaeger-agentgateway-", delete=False) as handle:
                temporary = Path(handle.name)
                with urllib.request.urlopen(RELEASE_URL, timeout=120) as response:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
            digest = _sha256(temporary)
            if digest != SHA256:
                temporary.unlink(missing_ok=True)
                raise InstallError(
                    f"Agentgateway checksum mismatch: expected {SHA256}, got {digest}"
                )
            temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            os.replace(temporary, destination)

    _link_command(destination, jaeger_link)
    _link_command(destination, user_link)
    return destination


def main(argv: list[str] | None = None) -> int:
    del argv
    path = install_binary()
    print(f"Agentgateway {VERSION} at {path}")
    print(f"Command link: {binary_link()} (and ~/.local/bin/agentgateway)")
    print(f"Home: {jaeger_home()}")
    return 0
