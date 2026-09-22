"""Library collections — folder-backed knowledge sources the user owns.

Library holds *knowledge owned by the person* (see
``docs/architecture/PRODUCT_SURFACES.md``): an Obsidian vault, a local notes
folder, a mounted network share of books and PDFs. Each collection is a rooted,
read-only path plus a label.

Deliberately separate from the Workshop workspace registry: a workspace is a
place you *build* in and write to, a collection is a corpus you *study*. Reusing
the workspace registry would have blurred that boundary and made every vault
look like a build root.

Indexing/RAG configuration is **not** here — that is Memory Infrastructure and
belongs to System. This module only registers, validates, and reads.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# Files worth surfacing in a knowledge corpus. Anything else is listed but not
# openable, so a vault full of attachments still browses sensibly.
READABLE_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".org",
    ".json", ".yaml", ".yml", ".toml", ".csv",
}

DOCUMENT_SUFFIXES = {".pdf", ".epub", ".mobi", ".djvu"}

# Guard rails for reading a single note into the browser.
MAX_READ_BYTES = 2_000_000

_COLLECTION_KINDS = ("obsidian", "folder", "network")


class LibraryError(ValueError):
    """Raised for user-correctable problems (bad path, duplicate, missing)."""


def _ares_home() -> Path:
    return Path(os.environ.get("JAEGER_HOME", os.environ.get("ARES_HOME", Path.home() / ".jaeger")))


def _store_path() -> Path:
    return _ares_home().expanduser() / "library" / "collections.json"


def _load() -> list[dict[str, Any]]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in data.get("collections", []) if isinstance(row, dict)]


def _save(collections: list[dict[str, Any]]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"collections": collections}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _slug(label: str, taken: set[str]) -> str:
    base = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")
    base = "-".join(filter(None, base.split("-"))) or "collection"
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def detect_kind(root: Path) -> str:
    """Classify a folder so the UI can label it without asking the user."""
    if (root / ".obsidian").is_dir():
        return "obsidian"
    # Network mounts on macOS live under /Volumes; on Linux under /mnt or /media.
    parts = root.resolve().parts
    if len(parts) > 1 and parts[1] in {"Volumes", "mnt", "media"}:
        return "network"
    return "folder"


def _resolve_root(raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if not str(candidate):
        raise LibraryError("A folder path is required")
    try:
        root = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise LibraryError(f"Path not found: {candidate}") from exc
    if not root.is_dir():
        raise LibraryError(f"Not a folder: {root}")
    if not os.access(root, os.R_OK):
        raise LibraryError(f"Folder is not readable: {root}")
    return root


def _stat_collection(root: Path) -> dict[str, Any]:
    """Cheap corpus summary — capped so a huge vault cannot stall the request."""
    notes = documents = other = 0
    scanned = 0
    reachable = True
    try:
        for entry in root.rglob("*"):
            if scanned >= 20_000:
                break
            if entry.name.startswith("."):
                continue
            if not entry.is_file():
                continue
            scanned += 1
            suffix = entry.suffix.lower()
            if suffix in READABLE_SUFFIXES:
                notes += 1
            elif suffix in DOCUMENT_SUFFIXES:
                documents += 1
            else:
                other += 1
    except (OSError, PermissionError):
        reachable = False
    return {
        "notes": notes,
        "documents": documents,
        "other": other,
        "truncated": scanned >= 20_000,
        "reachable": reachable,
    }


def _public(row: dict[str, Any], *, include_stats: bool = True) -> dict[str, Any]:
    root = Path(str(row.get("path") or "")).expanduser()
    exists = root.is_dir()
    out = {
        "id": row.get("id"),
        "label": row.get("label"),
        "path": str(root),
        "kind": row.get("kind") or "folder",
        "added_at": row.get("added_at"),
        "available": exists,
    }
    if include_stats and exists:
        out["stats"] = _stat_collection(root)
    elif include_stats:
        # A disconnected network share should read as unavailable, not empty.
        out["stats"] = {
            "notes": 0, "documents": 0, "other": 0,
            "truncated": False, "reachable": False,
        }
    return out


def list_collections(*, include_stats: bool = True) -> dict[str, Any]:
    rows = _load()
    return {"collections": [_public(row, include_stats=include_stats) for row in rows]}


def add_collection(path: str, label: str = "", kind: str = "") -> dict[str, Any]:
    root = _resolve_root(path)
    rows = _load()
    if any(Path(str(r.get("path"))).expanduser() == root for r in rows):
        raise LibraryError(f"Already connected: {root}")

    resolved_kind = kind if kind in _COLLECTION_KINDS else detect_kind(root)
    clean_label = str(label or "").strip() or root.name or str(root)
    row = {
        "id": _slug(clean_label, {str(r.get("id")) for r in rows}),
        "label": clean_label,
        "path": str(root),
        "kind": resolved_kind,
        "added_at": time.time(),
    }
    rows.append(row)
    _save(rows)
    return _public(row)


def remove_collection(collection_id: str) -> dict[str, Any]:
    rows = _load()
    remaining = [r for r in rows if str(r.get("id")) != str(collection_id)]
    if len(remaining) == len(rows):
        raise LibraryError(f"No such collection: {collection_id}")
    _save(remaining)
    return {"ok": True, "removed": collection_id}


def rename_collection(collection_id: str, label: str) -> dict[str, Any]:
    clean = str(label or "").strip()
    if not clean:
        raise LibraryError("A label is required")
    rows = _load()
    for row in rows:
        if str(row.get("id")) == str(collection_id):
            row["label"] = clean
            _save(rows)
            return _public(row)
    raise LibraryError(f"No such collection: {collection_id}")


def _collection_root(collection_id: str) -> tuple[dict[str, Any], Path]:
    for row in _load():
        if str(row.get("id")) == str(collection_id):
            root = Path(str(row.get("path"))).expanduser()
            if not root.is_dir():
                raise LibraryError(f"Collection is unavailable: {row.get('label')}")
            return row, root.resolve()
    raise LibraryError(f"No such collection: {collection_id}")


def _safe_target(root: Path, relative: str) -> Path:
    """Resolve *relative* inside *root*, refusing traversal and symlink escapes."""
    target = (root / str(relative or "").lstrip("/")).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise LibraryError("Path is outside the collection") from exc
    return target


def browse(collection_id: str, path: str = ".") -> dict[str, Any]:
    _, root = _collection_root(collection_id)
    target = _safe_target(root, path)
    if not target.is_dir():
        raise LibraryError("Not a folder")

    entries: list[dict[str, Any]] = []
    try:
        for item in sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        ):
            if item.name.startswith("."):
                continue
            is_dir = item.is_dir()
            suffix = item.suffix.lower()
            entries.append({
                "name": item.name,
                "path": str(item.relative_to(root)),
                "kind": "directory" if is_dir else "file",
                "readable": (not is_dir) and suffix in READABLE_SUFFIXES,
                "document": (not is_dir) and suffix in DOCUMENT_SUFFIXES,
                "size": None if is_dir else item.stat().st_size,
            })
    except (OSError, PermissionError) as exc:
        raise LibraryError(f"Could not read folder: {exc}") from exc

    return {
        "collection_id": collection_id,
        "path": "." if target == root else str(target.relative_to(root)),
        "entries": entries,
    }


def read_item(collection_id: str, path: str) -> dict[str, Any]:
    _, root = _collection_root(collection_id)
    target = _safe_target(root, path)
    if not target.is_file():
        raise LibraryError("Not a file")

    suffix = target.suffix.lower()
    size = target.stat().st_size
    if suffix not in READABLE_SUFFIXES:
        # PDFs/EPUBs are listed but not inlined — extraction is a later pass.
        return {
            "collection_id": collection_id,
            "path": str(target.relative_to(root)),
            "name": target.name,
            "readable": False,
            "size": size,
            "reason": "binary_or_unsupported",
            "content": "",
        }
    if size > MAX_READ_BYTES:
        raise LibraryError("File is too large to open here")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError) as exc:
        raise LibraryError(f"Could not read file: {exc}") from exc

    return {
        "collection_id": collection_id,
        "path": str(target.relative_to(root)),
        "name": target.name,
        "readable": True,
        "size": size,
        "content": content,
    }
