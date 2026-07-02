"""macOS host control — one tool, ``open_on_host``.

Three near-identical wrappers around the macOS ``open`` command
(launch a URL, open a workspace file, launch an app) used to be three
separate tools. They are one now: ``open_on_host(target)`` auto-detects
which kind of target it got, so the agent has a single, unambiguous
verb for "put this in front of the user."

File targets are sandbox-resolved to <instance>/skills/ (the agent's
writable area) — only files the agent itself authored, or that already
live in skills/, can be opened.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from jaeger_os.core.context import SandboxError, _require_layout, _resolve_under


def _run_open(args: list[str], label: dict[str, Any]) -> dict[str, Any]:
    """Run ``open`` with ``args``; fold the result into ``label``."""
    if platform.system() != "Darwin":
        return {"error": f"open_on_host only supported on macOS (got {platform.system()})", **label}
    try:
        result = subprocess.run(["open", *args], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], **label}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), **label}
    return {"opened": True, **label}


def open_on_host(target: str, kind: str = "auto") -> dict[str, Any]:
    """Open a URL, a workspace file, or a macOS app on the host.

    ``kind`` is one of ``"auto"`` (default), ``"url"``, ``"file"``,
    ``"app"``. With ``"auto"`` the target is classified:

      • starts with http:// or https://  → opened as a URL
      • resolves to an existing file under skills/ → opened as a file
      • otherwise → treated as an app name (``open -a``)
    """
    clean = (target or "").strip()
    if not clean:
        return {"error": "empty target"}
    kind = (kind or "auto").strip().lower()

    is_url = clean.startswith("http://") or clean.startswith("https://")
    if kind == "auto":
        if is_url:
            kind = "url"
        else:
            # File if it resolves inside skills/ and exists; else app.
            try:
                layout = _require_layout()
                resolved = _resolve_under(layout.skills_dir, clean)
                kind = "file" if resolved.exists() else "app"
            except (SandboxError, Exception):  # noqa: BLE001
                kind = "app"

    if kind == "url":
        if not is_url:
            return {"error": "URL must start with http:// or https://", "url": clean}
        return _run_open([clean], {"url": clean})

    if kind == "file":
        layout = _require_layout()
        try:
            resolved = _resolve_under(layout.skills_dir, clean)
        except SandboxError as exc:
            return {"error": str(exc), "path": clean}
        if not resolved.exists():
            return {"error": "file not found", "path": clean}
        return _run_open([str(resolved)], {"path": str(resolved.relative_to(layout.root))})

    if kind == "app":
        return _run_open(["-a", clean], {"app": clean})

    return {"error": f"unknown kind {kind!r} (use auto/url/file/app)", "target": clean}
