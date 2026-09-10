"""Safe, audited workspace file and git tools scoped to granted roots."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .grants import MAX_BYTES, _audit, _require, _resolve


def workspace_list(path: str = "/workspace", recursive: bool = False, max_items: int = 100) -> dict[str, Any]:
    """List directory contents within approved workspace roots."""
    capability = "workspace.list"
    _require(capability)
    target = _resolve(path, capability=capability)
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    items = []
    limit = max(1, min(int(max_items), 1000))
    if recursive:
        for root, dirs, files in os.walk(target):
            for d in dirs:
                items.append({"path": str(Path(root, d).relative_to(target)), "type": "directory"})
                if len(items) >= limit:
                    break
            for f in files:
                p = Path(root, f)
                items.append({"path": str(p.relative_to(target)), "type": "file", "size": p.stat().st_size if p.exists() else 0})
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
    else:
        for entry in target.iterdir():
            items.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
            if len(items) >= limit:
                break
    _audit(capability, outcome="allowed", path=target)
    return {"path": str(target), "items": items, "total": len(items)}


def workspace_read(path: str, max_bytes: int = 100_000) -> dict[str, Any]:
    """Read a text file within approved workspace roots."""
    capability = "workspace.read"
    _require(capability)
    target = _resolve(path, capability=capability)
    if not target.is_file():
        raise FileNotFoundError(str(target))
    size = target.stat().st_size
    read_limit = max(1, min(int(max_bytes), MAX_BYTES))
    content = target.read_bytes()[:read_limit].decode("utf-8", errors="replace")
    _audit(capability, outcome="allowed", path=target)
    return {
        "path": str(target),
        "size": size,
        "truncated": size > read_limit,
        "content": content,
    }


def workspace_write(path: str, content: str, overwrite: bool = True) -> dict[str, Any]:
    """Write text content to a file within approved workspace roots."""
    capability = "workspace.write"
    _require(capability)
    target = _resolve(path, must_exist=False, capability=capability)
    if target.exists() and not overwrite:
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _audit(capability, outcome="allowed", path=target)
    return {"path": str(target), "bytes_written": len(content.encode("utf-8"))}


def workspace_mkdir(path: str) -> dict[str, Any]:
    """Create a directory within approved workspace roots."""
    capability = "workspace.mkdir"
    _require(capability)
    target = _resolve(path, must_exist=False, capability=capability)
    target.mkdir(parents=True, exist_ok=True)
    _audit(capability, outcome="allowed", path=target)
    return {"path": str(target), "created": True}


def workspace_move(source: str, destination: str) -> dict[str, Any]:
    """Move or rename a file or directory within approved workspace roots."""
    capability = "workspace.move"
    _require(capability)
    src = _resolve(source, capability=capability)
    dst = _resolve(destination, must_exist=False, capability=capability)
    if dst.exists():
        raise FileExistsError(str(dst))
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    _audit(capability, outcome="allowed", path=dst)
    return {"moved": True, "source": str(src), "destination": str(dst)}


def workspace_delete(path: str) -> dict[str, Any]:
    """Delete a file or empty directory within approved workspace roots."""
    capability = "workspace.delete"
    _require(capability)
    target = _resolve(path, must_exist=True, capability=capability)
    if target.is_dir() and any(target.iterdir()):
        _audit(capability, outcome="denied", path=target, error="directory not empty")
        raise ValueError("Directory is not empty; delete its contents first")
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink()
    _audit(capability, outcome="allowed", path=target)
    return {"deleted": True, "path": str(target)}


def git_status(path: str = "/workspace") -> dict[str, Any]:
    """Run read-only git status on an approved workspace repository."""
    capability = "git.status"
    _require(capability)
    target = _resolve(path, capability=capability)
    if target.is_file():
        target = target.parent
    proc = subprocess.run(
        ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "status", "--short", "--branch"],
        cwd=target,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    _audit(capability, outcome="allowed" if proc.returncode == 0 else "failed", path=target)
    return {"path": str(target), "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def git_diff(path: str = "/workspace") -> dict[str, Any]:
    """Run read-only git diff on an approved workspace repository."""
    capability = "git.diff"
    _require(capability)
    target = _resolve(path, capability=capability)
    if target.is_file():
        target = target.parent
    proc = subprocess.run(
        ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "--no-pager", "diff", "--no-ext-diff"],
        cwd=target,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    _audit(capability, outcome="allowed" if proc.returncode == 0 else "failed", path=target)
    return {"path": str(target), "exit_code": proc.returncode, "stdout": proc.stdout[:MAX_BYTES], "stderr": proc.stderr}
