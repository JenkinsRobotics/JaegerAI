"""Bounded, read-only access to an explicitly configured Obsidian vault."""

from __future__ import annotations

import os
import stat
from pathlib import Path

MAX_FILE_BYTES = 1_000_000
MAX_FILES_SCANNED = 5_000
MAX_RESULTS = 100
MAX_QUERY_LENGTH = 200


class VaultError(ValueError):
    pass


def vault_root() -> Path:
    raw = os.environ.get("JAEGER_OBSIDIAN_VAULT", "")
    if not raw:
        raise VaultError("Obsidian vault is disabled")
    root = Path(raw).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise VaultError("Obsidian vault must be an existing directory, not a symlink")
    return root.resolve(strict=True)


def _parts(path: str) -> tuple[str, ...]:
    candidate = Path(path)
    parts = candidate.parts
    if candidate.is_absolute() or not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
        raise VaultError("invalid vault note path")
    if parts[-1].lower().endswith(".md") is False:
        raise VaultError("only .md notes are supported")
    return parts


def _read(root: Path, path: str) -> str:
    parts = _parts(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        note_fd = os.open(parts[-1], flags, dir_fd=fd)
        try:
            info = os.fstat(note_fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                raise VaultError("note is not a regular file or exceeds size limit")
            with os.fdopen(note_fd, "rb", closefd=False) as note:
                data = note.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                raise VaultError("note exceeds size limit")
            return data.decode("utf-8", errors="replace")
        finally:
            os.close(note_fd)
    except OSError as exc:
        raise VaultError(f"cannot read note: {path}") from exc
    finally:
        os.close(fd)


def _paths(root: Path):
    scanned = 0
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if not name.startswith(".") and not (Path(directory) / name).is_symlink())
        for name in sorted(files):
            if name.startswith(".") or not name.lower().endswith(".md"):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                continue
            scanned += 1
            if scanned > MAX_FILES_SCANNED:
                return
            yield path.relative_to(root).as_posix()


def list_notes(limit: int = 50) -> dict:
    root = vault_root()
    limit = max(1, min(int(limit), MAX_RESULTS))
    notes = []
    for path in _paths(root):
        notes.append(path)
        if len(notes) >= limit:
            break
    return {"notes": notes, "limit": limit}


def read_note(path: str) -> dict:
    content = _read(vault_root(), path)
    front_matter = None
    body = content
    if content.startswith("---\n"):
        marker = content.find("\n---\n", 4)
        if marker >= 0:
            front_matter = content[4:marker]
            body = content[marker + 5:]
    return {"path": path, "front_matter": front_matter, "body": body}


def search_notes(query: str, limit: int = 20) -> dict:
    root = vault_root()
    if not query or len(query) > MAX_QUERY_LENGTH:
        raise VaultError("query must contain 1 to 200 characters")
    limit = max(1, min(int(limit), MAX_RESULTS))
    results = []
    needle = query.casefold()
    for path in _paths(root):
        try:
            content = _read(root, path)
        except VaultError:
            continue
        offset = content.casefold().find(needle)
        if offset < 0:
            continue
        results.append({"path": path, "snippet": content[max(0, offset - 80):offset + len(query) + 80]})
        if len(results) >= limit:
            break
    return {"results": results, "limit": limit}
