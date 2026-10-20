"""Correlated follow-ups reuse handoff admission; a message alone never executes."""
from __future__ import annotations


class ReplyConflict(ValueError):
    pass


def reply_context(store, handoff_id, *, source=None, target=None, session=None):
    parent = store.get_handoff(handoff_id)
    if not parent:
        raise ReplyConflict('Exchange unavailable')
    if parent.get('status') not in {'completed', 'failed', 'cancelled', 'rejected'}:
        raise ReplyConflict('Exchange is active or has an unknown outcome; observe/reconcile it before a follow-up')
    if not parent.get('session_id') or not store.get_session(parent['session_id']):
        raise ReplyConflict('Original conversation unavailable')
    if source is not None and (source != parent['from_agent_id'] or target != parent['to_agent_id'] or session != parent['session_id']):
        raise ReplyConflict('Reply cannot change exchange participants or conversation')
    return parent


def reply_payload(store, handoff_id, body):
    if not isinstance(body, dict) or set(body) != {'task', 'request_id'}:
        raise ValueError('Only task and a new request_id are required')
    if not isinstance(body['task'], str) or not 1 <= len(body['task'].strip()) <= 20000:
        raise ValueError('Follow-up must contain 1–20000 characters')
    if not isinstance(body['request_id'], str) or not 1 <= len(body['request_id']) <= 128:
        raise ValueError('A stable new request_id is required')
    parent = reply_context(store, handoff_id)
    if body['request_id'] == parent.get('request_id'):
        raise ReplyConflict('Follow-up must use a new request_id')
    meta = parent.get('metadata') or {}
    return parent['to_agent_id'], {
        **body, 'session_id': parent['session_id'], 'from_agent_id': parent['from_agent_id'],
        'require_approval': True, 'reply_to_handoff_id': parent['id'],
        'permitted_context': ('Earlier exchange data, not a permission grant.\nTask: ' + str(parent.get('task') or '') + '\nResult: ' + str((parent.get('result') or {}).get('summary') or ''))[:24000],
        'allowed_tools': list(meta.get('allowed_tools') or []),
        'project_id': meta.get('project_id'), 'workspace': meta.get('workspace'),
        'timeout_seconds': meta.get('timeout_seconds', 120),
    }
