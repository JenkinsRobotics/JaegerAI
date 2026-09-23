"""Shared helpers for ``jaeger`` subcommands."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


# ANSI colours — Rich would be heavier but adds polish.  These plain
# escapes keep the CLI dependency-free + grep-friendly in scripts.
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_RED = "\033[31m"
_GREY = "\033[90m"


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colour(text: str, code: str) -> str:
    """Wrap ``text`` with an ANSI colour code when stdout is a TTY."""
    if not _supports_color():
        return text
    return f"{code}{text}{_RESET}"


def bold(text: str) -> str: return colour(text, _BOLD)
def dim(text: str) -> str: return colour(text, _DIM)
def yellow(text: str) -> str: return colour(text, _YELLOW)
def green(text: str) -> str: return colour(text, _GREEN)
def cyan(text: str) -> str: return colour(text, _CYAN)
def red(text: str) -> str: return colour(text, _RED)
def grey(text: str) -> str: return colour(text, _GREY)


def get_active_instance_layout() -> Any:
    """Resolve the operator's currently-active instance.  Returns an
    ``InstanceLayout`` or ``None`` if no instance is configured yet."""
    try:
        from jaeger_ai.core.instance.instance import (
            InstanceLayout,
            default_instance_name,
            resolve_instance_dir,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        name = default_instance_name()
        root = resolve_instance_dir(name)
        return InstanceLayout(root=root)
    except Exception:  # noqa: BLE001
        return None


def list_known_instances() -> list[Path]:
    """Enumerate instance directories.

    Scans the **canonical** operator-state root (the install's
    ``.jaeger_ai/instances/`` — what the wizard and resolver use), plus the
    legacy ``~/.jaeger_ai`` so old installs still list. Wizard backups
    (``<name>.bak.<ts>``) are hidden. Returns one Path per instance root.
    """
    candidates: list[Path] = []

    def _scan(root: Path) -> None:
        if not root.exists():
            return
        for child in root.iterdir():
            if (child.is_dir() and (child / "manifest.json").exists()
                    and ".bak." not in child.name):
                candidates.append(child)

    # The canonical location first — install_root/.jaeger_ai/instances.
    try:
        from jaeger_ai.core.instance.instance import user_instances_root
        _scan(user_instances_root())
    except Exception:  # noqa: BLE001 — fall back to the legacy scans
        pass

    _scan(Path.home() / ".jaeger_ai" / "instances")

    # De-dup by absolute path while preserving order.
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        ap = p.resolve()
        if ap not in seen:
            seen.add(ap)
            out.append(p)
    return out


def bar(value: float, *, width: int = 16, ch_full: str = "█",
        ch_empty: str = "░") -> str:
    """Render a 0..1 value as an ASCII progress bar."""
    v = max(0.0, min(1.0, float(value)))
    fill = int(round(v * width))
    return ch_full * fill + ch_empty * (width - fill)


def kv(label: str, value: str, *, label_width: int = 20) -> str:
    """Render a key:value line for status outputs."""
    return f"  {label.ljust(label_width)} {value}"


def swift_build_dir(repo: Path) -> Path:
    """Canonical external SwiftPM build root. All callers must use this.

    Resolution order:
      1. ``JAEGER_SWIFT_BUILD`` env var
      2. ``~/.jaeger/apps/swift-build`` (default)

    Rejects paths that resolve inside the repo checkout and rejects
    dangerous broad roots (``/``, ``/Applications``, ``~``, ``/tmp``).
    Raises ``ValueError`` on an invalid override so the caller can report it.
    """
    raw = os.environ.get("JAEGER_SWIFT_BUILD", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
    else:
        p = (Path.home() / ".jaeger" / "apps" / "swift-build").resolve()
    repo_real = Path(repo).resolve()
    if p == repo_real or repo_real in p.parents:
        raise ValueError(
            f"JAEGER_SWIFT_BUILD ({p}) resolves inside the checkout ({repo_real}); "
            "set it to an external directory"
        )
    # Reject dangerous broad roots.
    for danger in (Path("/"), Path("/Applications"), Path("/tmp"), Path.home()):
        if p == danger.resolve():
            raise ValueError(
                f"JAEGER_SWIFT_BUILD ({p}) is a dangerous broad root; "
                "choose a dedicated subdirectory"
            )
    return p


def swift_app_bundle(repo: Path) -> Path:
    """Path to the JaegerAI.app produced by build-app.sh (always external)."""
    return swift_build_dir(repo) / "JaegerAI.app"


def _swift_source_fingerprint(repo: Path) -> str:
    """SHA-256 of all build inputs under jaeger_ai/interfaces/swift/.

    Walks the tree deterministically, hashing relative paths and file
    contents. Excludes .build/ scratch. Works on dirty, untracked, and
    newly-deleted files. Returns '' if the source directory does not exist.
    """
    import hashlib

    swift_dir = (Path(repo) / "jaeger_ai" / "interfaces" / "swift").resolve()
    if not swift_dir.is_dir():
        return ""
    h = hashlib.sha256()
    for root, dirs, files in os.walk(str(swift_dir)):
        dirs[:] = sorted(d for d in dirs if d not in (".build",))
        root_path = Path(root)
        for fname in sorted(files):
            fpath = root_path / fname
            h.update(str(fpath.relative_to(swift_dir)).encode())
            try:
                h.update(fpath.read_bytes())
            except OSError:
                pass
    return h.hexdigest()


def swift_app_is_stale(repo: Path, bundle: Path) -> bool:
    """True when the built Swift app predates the current Swift sources.

    Reads Contents/Resources/build-source-hash written by build-app.sh —
    a SHA-256 over jaeger_ai/interfaces/swift/ captured before the build
    started. Covers uncommitted, dirty, and untracked source changes that
    a git-diff-only check would miss. Missing executable or missing stamp
    (legacy build / failed stamp) → stale. No .git (tarball install) → False.
    """
    exe = bundle / "Contents" / "MacOS" / "JaegerAI"
    if not exe.exists():
        return True
    if not (repo / ".git").exists():
        return False
    stamp = bundle / "Contents" / "Resources" / "build-source-hash"
    try:
        stored = stamp.read_text().strip()
    except OSError:
        stored = ""
    if not stored:
        return True
    return _swift_source_fingerprint(repo) != stored
