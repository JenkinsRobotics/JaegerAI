"""Workspace resolution for the web app's read-only file and Git views."""
from __future__ import annotations

import os
from pathlib import Path

_STATE = Path(os.environ.get("JAEGER_WEBUI_STATE_DIR") or Path.home() / ".jaeger/hermes-webui-state")
_SENSITIVE = (".ssh", ".gnupg", "Library/Keychains", ".jaeger/instances/jaeger/credentials")


def get_last_workspace() -> str:
    try:
        return (_STATE / "last_workspace.txt").read_text().strip()
    except OSError:
        return str(Path.home() / "workspace")


def resolve_trusted_workspace(path: str) -> Path:
    root = Path(path).expanduser().resolve()
    home = Path.home().resolve()
    if not root.is_dir():
        raise ValueError("workspace is not a directory")
    if root != home and not root.is_relative_to(home):
        raise ValueError("workspace is outside your home folder")
    if any(str(root).endswith(s) or f"/{s}/" in f"{root}/" for s in _SENSITIVE):
        raise ValueError("workspace is a protected folder")
    return root
