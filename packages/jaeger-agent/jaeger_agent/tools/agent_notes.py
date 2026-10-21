"""agent_notes — a specialist's own memory file (``memory/agents/<name>/NOTES.md``).

The Gateway (jaegerd) binds the directory for the duration of a specialist
turn; the model never names a path, so one agent cannot read or write another
agent's notes, and outside a specialist turn the tool refuses.
"""
from __future__ import annotations

import contextlib
import contextvars
from pathlib import Path
from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function

NOTES_MAX_CHARS = 16000
_notes_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar("jaeger_agent_notes_dir", default=None)


@contextlib.contextmanager
def bound_notes_dir(path: Path | None):
    token = _notes_dir.set(Path(path) if path else None)
    try:
        yield
    finally:
        _notes_dir.reset(token)


NOTES_PROMPT_CHARS = 4000
NOTES_READ_MAX_BYTES = 1_000_000


def _read_bytes(path: Path) -> bytes:
    import os, stat
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b''
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Notes must be a regular file')
        value = stream.read(NOTES_READ_MAX_BYTES + 1)
    if len(value) > NOTES_READ_MAX_BYTES:
        raise ValueError('Notes exceed the supported read size; original preserved')
    return value


def read_notes(root: Path) -> dict[str, Any]:
    import hashlib
    data = _read_bytes(root / 'NOTES.md')
    text = data.decode('utf-8')
    return {'notes': text, 'revision': hashlib.sha256(data).hexdigest(), 'chars': len(text),
            'prompt_chars': NOTES_PROMPT_CHARS, 'max_chars': NOTES_MAX_CHARS,
            'prompt_truncated': len(text) > NOTES_PROMPT_CHARS}


def _versions(root: Path) -> Path:
    path = root / '.versions'
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Notes version directory escapes its owner')
    return path


def note_versions(root: Path) -> list[dict[str, Any]]:
    import re
    directory = _versions(root)
    if not directory.is_dir(): return []
    files = [p for p in directory.iterdir() if re.fullmatch(r'[a-f0-9]{64}\.md', p.name) and not p.is_symlink()]
    return [{'revision': p.stem, 'saved_at': p.stat().st_mtime} for p in sorted(files,key=lambda p:p.stat().st_mtime,reverse=True)[:50]]


def mutate_notes(root: Path, action: str, text: str = '', *, expected_revision: str | None = None, restore_revision: str | None = None) -> dict[str, Any]:
    """One locked writer for both agent tool and operator API; preserve prior bytes.

    Generic/manual filesystem writers do not participate in this protocol.
    Ordinary notes owners must use this function, never duplicate its write path.
    """
    import fcntl, hashlib, os, re, tempfile
    root.mkdir(parents=True,exist_ok=True)
    lock = os.open(root / '.notes.lock',os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        original = _read_bytes(root / 'NOTES.md')
        current = original.decode('utf-8')
        revision = hashlib.sha256(original).hexdigest()
        if expected_revision is not None and expected_revision != revision:
            raise ValueError('Notes changed; reload and review before saving')
        if action == 'restore':
            if not restore_revision or not re.fullmatch(r'[a-f0-9]{64}',restore_revision):raise ValueError('Invalid saved notes revision')
            saved_path = _versions(root) / (restore_revision + '.md')
            if not saved_path.is_file() or saved_path.is_symlink():raise ValueError('Saved revision missing or unsafe')
            saved = _read_bytes(saved_path)
            if hashlib.sha256(saved).hexdigest() != restore_revision:raise ValueError('Saved revision missing or changed')
            new = saved.decode('utf-8')
        else:
            body = str(text or '').strip()
            if not body:raise ValueError('text is required; empty destructive clears are unavailable')
            if action not in {'append','replace'}:raise ValueError('action must be append, replace or restore')
            new = (current.rstrip() + '\n' + body + '\n').lstrip() if action == 'append' else body + '\n'
        if not new.strip():raise ValueError('Empty destructive clears are unavailable')
        if len(new) > NOTES_MAX_CHARS:raise ValueError(f'notes would exceed {NOTES_MAX_CHARS} characters; original preserved')
        if (root/'NOTES.md').exists() and not ((root/'NOTES.md').stat().st_mode & 0o222):raise ValueError('Notes file is read-only; original permissions preserved')
        versions = _versions(root);versions.mkdir(mode=0o700,exist_ok=True)
        if original:
            archive = versions / (revision + '.md')
            if archive.exists():
                if _read_bytes(archive) != original:raise ValueError('Saved notes revision conflicts; original preserved')
            else:
                fd = os.open(archive,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(original);stream.flush();os.fsync(stream.fileno())
        fd,tmp = tempfile.mkstemp(prefix='.notes-',dir=root)
        try:
            # Preserve existing note permissions on replacement.
            if (root / 'NOTES.md').exists():os.fchmod(fd,(root / 'NOTES.md').stat().st_mode & 0o777)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(new);stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,root / 'NOTES.md')
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        data = new.encode('utf-8')
        return {'notes':new,'revision':hashlib.sha256(data).hexdigest(),'chars':len(new),'prompt_chars':NOTES_PROMPT_CHARS,'max_chars':NOTES_MAX_CHARS,'prompt_truncated':len(new)>NOTES_PROMPT_CHARS}
    finally:
        fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)


@register_tool_from_function(name="agent_notes", side_effect="write")
def agent_notes(action: str = "read", text: str = "", expected_revision: str | None = None) -> dict[str, Any]:
    """Your own specialist notes. Read returns a revision; append/replace can
    supply expected_revision to reject stale edits. Previous notes are preserved.
    No path can be supplied by the model; Gateway binds this agent's directory.
    """
    root = _notes_dir.get()
    if root is None:
        return {"ok": False, "error": "agent_notes is only available to a specialist agent"}
    try:
        if (action or 'read').strip().lower() == 'read':return {'ok':True,**read_notes(root)}
        return {'ok':True,**mutate_notes(root,action.strip().lower(),text,expected_revision=expected_revision)}
    except (OSError,ValueError) as exc:
        return {'ok':False,'error':str(exc)}
