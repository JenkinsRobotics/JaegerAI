"""Read-only artifact references over owner-verified durable task receipts.

No path from HTTP/model output becomes a file grant. Reopening requires both
an owner verification receipt and the unchanged originating session workspace.
Nothing is copied, registered as an upload, executed or imported into memory.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path

from jaeger_os.core.safety.file_safety import is_sensitive_path

from .models import TaskState


def references(gateway, task):
    if task.state is not TaskState.COMPLETED_VERIFIED:
        return []
    evidence = task.payload.get('verification')
    if not isinstance(evidence, list):
        return []
    session_id = str(task.provenance.get('session_id') or '')
    session = gateway.store.get_session(session_id) if session_id else None
    workspace = (task.payload.get('execution') or {}).get('workspace')
    if not isinstance(workspace, str) or not workspace:
        return []
    root = Path(workspace).expanduser().resolve()
    result = {}
    for receipt in evidence:
        if not isinstance(receipt, dict) or receipt.get('kind') not in (None, 'file_sha256', 'owner_file_sha256'):
            continue
        raw, digest = receipt.get('resolved') or receipt.get('path'), receipt.get('sha256')
        if not isinstance(raw, str) or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            continue
        original = Path(raw).expanduser()
        original = original if original.is_absolute() else root / original
        original = Path(os.path.abspath(original))
        if not original.is_relative_to(root) or is_sensitive_path(original):
            continue
        # Identity uses the saved receipt, never a fresh file stat, alias, task
        # index, presentation name or model-supplied result string.
        aid = 'artifact_' + hashlib.sha256(json.dumps([task.task_id, raw, digest]).encode()).hexdigest()[:32]
        name = original.name or 'Artifact'
        reason = None
        size = 0
        try:
            path = original.resolve()
            if not path.is_relative_to(root) or is_sensitive_path(path):
                raise ValueError('Artifact target changed or is sensitive')
            if not session or not session.get('workspace') or Path(session['workspace']).expanduser().resolve() != root:
                raise ValueError('Originating workspace access is unavailable; artifact bytes withheld')
            size = path.stat().st_size
            if size > gateway.UPLOAD_MAX_BYTES:
                raise ValueError('Artifact exceeds supported read size')
            if not path.is_file():
                raise ValueError('Artifact is not a regular file')
        except (OSError, ValueError):
            reason = 'Artifact missing or originating workspace unavailable; no new access granted'
        row = {'attachment_id': aid, 'session_id': session_id, 'original_filename': name,
               'safe_path': str(original), 'mime_type': mimetypes.guess_type(name)[0] or 'application/octet-stream',
               'size_bytes': size, 'sha256': digest, 'provenance': 'verified_task_artifact'}
        result[aid] = {'task_id': task.task_id, 'task_title': task.goal, 'session_id': session_id,
                       'attachment_id': aid, 'name': name, 'mime': row['mime_type'], 'size': size,
                       'sha256': digest, 'readable': reason is None, 'unavailable_reason': reason, '_row': row}
    return list(result.values())


def catalog(gateway, task_id=None, session_id=None):
    task = gateway.task_owner.store.get_task(task_id) if task_id else None
    tasks = [task] if task else [] if task_id else gateway.task_owner.store.list_tasks()
    return [{k: v for k, v in ref.items() if k != '_row'} for task in tasks for ref in references(gateway, task) if session_id is None or ref['session_id'] == session_id]


async def read(gateway, request):
    from aiohttp import web
    task = gateway.task_owner.store.get_task(request.match_info['task_id'])
    refs = references(gateway, task) if task else []
    ref = next((r for r in refs if r['attachment_id'] == request.match_info['artifact_id']), None)
    if ref is None:
        return web.json_response({'error': 'Verified artifact reference not found'}, status=404)
    if not ref['readable']:
        return web.json_response({'error': ref['unavailable_reason']}, status=409)
    session = gateway.store.get_session(ref['session_id'])
    return await gateway._session_file_response(request, ref['_row'], session)
