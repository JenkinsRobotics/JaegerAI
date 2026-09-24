"""Durable, turn-owned file-tool edits. Never restore an entire worktree.

The journal lives beside the Gateway database. Payloads are private; SSE
contains only filenames/counts. Undo checks every postimage before writing.
Unsupported/binary/large files are not advertised as undoable.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
import uuid


class FileChanges:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.RLock()

    def _journal(self, session: str, request: str) -> Path:
        key = hashlib.sha256(f"{session}\0{request}".encode()).hexdigest()
        return self.root / f"{key}.json"

    @staticmethod
    def _read(path: Path) -> dict:
        # Refuse symlinks in the entire path, including changed parent dirs.
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Refusing a symlink target")
        if not path.exists():
            return {"text": None, "mode": None}
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
            raise ValueError("Only regular text files up to 2 MiB are supported")
        text = path.read_bytes().decode("utf-8")
        if "\0" in text:
            raise ValueError("Binary file")
        return {"text": text, "mode": stat.S_IMODE(info.st_mode)}

    def begin(self, path: Path) -> dict:
        path = path.absolute()
        return {"path": str(path), "before": self._read(path)}

    def _load(self, session: str, request: str) -> dict:
        path = self._journal(session, request)
        return json.loads(path.read_text()) if path.exists() else {"files": [], "undone": False}

    def _save(self, session: str, request: str, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self._journal(session, request)
        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(data, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, target)

    def finish(self, session: str, request: str, snapshot: dict) -> None:
        with self.lock:
            after = self._read(Path(snapshot["path"]))
            if after == snapshot["before"]:
                return
            data = self._load(session, request)
            previous = next((f for f in data["files"] if f["path"] == snapshot["path"]), None)
            if previous:
                # An intervening external edit cannot become this turn's edit.
                previous["conflict"] = previous.get("conflict", False) or previous["after"] != snapshot["before"]
                previous["after"] = after
            else:
                data["files"].append({**snapshot, "after": after, "conflict": False})
            self._save(session, request, data)

    def describe(self, session: str, request: str, *, contents: bool = False) -> dict:
        with self.lock:
            data = self._load(session, request)
            rows = []
            for f in data["files"]:
                before, after = f["before"]["text"] or "", f["after"]["text"] or ""
                added = removed = 0
                for tag, a, b, c, d in difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False).get_opcodes():
                    if tag in ("replace", "delete"): removed += b - a
                    if tag in ("replace", "insert"): added += d - c
                try:
                    unchanged = self._read(Path(f["path"])) == f["after"]
                except (OSError, ValueError, UnicodeError):
                    unchanged = False
                row = {"path": f["path"], "added": added, "removed": removed,
                       "conflict": f["conflict"] or not unchanged}
                if contents:
                    row.update(before=before, after=after, diff="\n".join(difflib.unified_diff(
                        before.splitlines(), after.splitlines(), fromfile=f["path"], tofile=f["path"], lineterm="")))
                rows.append(row)
            return {"requestId": request, "files": rows, "undone": data["undone"],
                    "canUndo": bool(rows) and not data["undone"] and not any(f["conflict"] for f in rows)}

    def undo(self, session: str, request: str) -> dict:
        with self.lock:
            data = self._load(session, request)
            if not self.describe(session, request)["canUndo"]:
                raise ValueError("Undo refused: no reversible changes, already undone, or files changed since this turn")
            # Each write rechecks its postimage. Record each successful reversal
            # durably so an I/O failure cannot cause a retry to overwrite it.
            for f in data["files"]:
                path = Path(f["path"])
                if self._read(path) != f["after"]:
                    raise ValueError(f"Undo refused: {path.name} changed")
                before = f["before"]
                if before["text"] is None:
                    path.unlink()  # original content remains recoverable in journal
                else:
                    temp = path.with_name(f".{path.name}.jaeger-undo-{uuid.uuid4().hex}")
                    try:
                        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, before["mode"])
                        os.fchmod(fd, before["mode"])
                        with os.fdopen(fd, "wb") as out:
                            out.write(before["text"].encode("utf-8"))
                        os.replace(temp, path)
                    finally:
                        temp.unlink(missing_ok=True)
                f["conflict"] = True  # prevents retry after a partially completed undo
                self._save(session, request, data)
            data["undone"] = True
            self._save(session, request, data)
            return self.describe(session, request)
