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
    ``.jaeger_os/instances/`` — what the wizard and resolver use), plus the
    legacy ``~/.jaeger_os`` so old installs still list. Wizard backups
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

    # The canonical location first — install_root/.jaeger_os/instances.
    try:
        from jaeger_ai.core.instance.instance import user_instances_root
        _scan(user_instances_root())
    except Exception:  # noqa: BLE001 — fall back to the legacy scans
        pass

    _scan(Path.home() / ".jaeger_os" / "instances")

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


def swift_app_is_stale(repo: Path, bundle: Path) -> bool:
    """True when the built Swift app predates the current Swift sources.

    The bundle carries a ``Contents/Resources/build-commit`` stamp written by
    build-app.sh. The app is stale when the Swift tree
    (``jaeger_os/interfaces/swift/``) differs between that commit and HEAD —
    which catches manual ``git pull``s that no update command saw. Missing
    executable or missing stamp (pre-stamp build) → stale. No ``.git``
    (clean/tarball install) → False; the tarball updater rebuilds explicitly
    after every product swap instead.
    """
    import subprocess

    exe = bundle / "Contents" / "MacOS" / "JaegerOS"
    if not exe.exists():
        return True
    if not (repo / ".git").exists():
        return False
    stamp = bundle / "Contents" / "Resources" / "build-commit"
    try:
        have = stamp.read_text().strip()
    except OSError:
        have = ""
    if not have:
        return True
    diff = subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", have, "HEAD",
         "--", "jaeger_os/interfaces/swift"],
        capture_output=True,
    )
    # 0 = tree unchanged since the build; anything else (1 = differs,
    # >1 = unknown commit after a history rewrite) → rebuild.
    return diff.returncode != 0
