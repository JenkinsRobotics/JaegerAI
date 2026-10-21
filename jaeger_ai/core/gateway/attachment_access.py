"""Session-bound attachment reads from the existing store; no path supplied by clients."""
from __future__ import annotations
import base64
import hashlib
from pathlib import Path


def resolve(row: dict, *, staged_root: Path, workspace: str) -> Path:
    path = Path(row.get('safe_path') or '').resolve()
    root = staged_root if row.get('provenance') == 'upload_staged' else Path(workspace) if workspace else None
    if root is None or not path.is_relative_to(root.resolve()):
        raise ValueError('Attachment is outside its current originating workspace')
    if row.get('provenance') == 'verified_task_artifact':
        from jaeger_os.core.safety.file_safety import is_sensitive_path
        if is_sensitive_path(path):
            raise ValueError('Sensitive artifact bytes are unavailable')
    if not row.get('sha256'):
        raise ValueError('Legacy attachment has no immutable digest; access unavailable')
    return path


def read(row: dict, *, staged_root: Path, workspace: str, limit: int) -> dict:
    path = resolve(row, staged_root=staged_root, workspace=workspace)
    size = int(row.get('size_bytes') or 0)
    if size < 0 or size > limit:
        raise ValueError('Attachment exceeds supported read size')
    # Walk beneath an opened root without following swapped parent symlinks.
    # No arbitrary path supplied by the caller is accepted.
    import os
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    root = (staged_root if row.get('provenance') == 'upload_staged' else Path(workspace)).resolve()
    relative = path.relative_to(root)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, directory_flags)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(relative.parts[-1], flags, dir_fd=directory)
    finally:
        os.close(directory)
    with os.fdopen(fd, 'rb') as stream:
        import stat
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise ValueError('Attachment file changed or is not a regular file')
        data = stream.read(limit + 1)
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != size or digest != row['sha256']:
        raise ValueError('Attachment bytes changed since registration; original withheld')
    return {'attachment_id': row['attachment_id'], 'name': row.get('original_filename') or 'attachment',
            'mime': row.get('mime_type') or 'application/octet-stream', 'size': size,
            'sha256': digest, 'data_base64': base64.b64encode(data).decode('ascii')}
