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


def mac_shell_build_dir(repo: Path) -> Path:
    """External build home for the canonical macos-shell target."""
    raw = os.environ.get("JAEGER_MAC_BUILD", "").strip()
    target = Path(raw).expanduser().resolve() if raw else (Path.home() / ".cache/jaeger/macos-shell").resolve()
    source = Path(repo).resolve()
    if target == source or source in target.parents:
        raise ValueError("JAEGER_MAC_BUILD must be outside the repository")
    if target in {p.resolve() for p in (Path('/'), Path('/Applications'), Path('/tmp'), Path.home())}:
        raise ValueError("JAEGER_MAC_BUILD must be a dedicated build directory")
    return target


def mac_app_bundle(repo: Path) -> Path:
    return mac_shell_build_dir(repo) / "JaegerShell.app"


def mac_app_is_stale(repo: Path, bundle: Path) -> bool:
    if not (bundle / "Contents/MacOS/JaegerShell").is_file():
        return True
    try:
        return (bundle / "Contents/Resources/build-source-hash").read_text().strip() != mac_source_fingerprint(repo)
    except OSError:
        return True


def mac_source_fingerprint(repo: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    for relative in ("jaeger_ai/interfaces/macos-shell", "jaeger_ai/interfaces/ui"):
        for root, directories, files in os.walk(Path(repo) / relative):
            directories[:] = sorted(d for d in directories if d not in {".build", "node_modules", "dist", "Jaeger Dev.app"})
            for name in sorted(files):
                path = Path(root) / name
                digest.update(str(path.relative_to(repo)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()
