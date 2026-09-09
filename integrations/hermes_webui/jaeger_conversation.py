"""Jaeger-profile chat continuity, using the configured native chat gateway."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import yaml


def native(action='', body=None):
    from api.profiles import get_active_profile_name, get_active_hermes_home
    if get_active_profile_name() != 'jaeger':
        raise ValueError('Select the Jaeger profile first')
    config = yaml.safe_load((get_active_hermes_home() / 'config.yaml').read_text()) or {}
    base = str(config.get('webui_gateway_base_url') or '').rstrip('/')
    key = str(config.get('webui_gateway_api_key') or '')
    if not base or not key:
        raise ValueError('Jaeger chat gateway is not configured')
    request = Request(base + '/v1/dispatcher/conversation' + ('/' + action if action else ''),
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def route(handler, parsed, method):
    if not parsed.path.startswith('/api/jaeger/conversation'):
        return False
    from api.helpers import j, read_body
    action = parsed.path.removeprefix('/api/jaeger/conversation').strip('/')
    if not ((method == 'GET' and not action) or
            (method == 'POST' and action in {'bind', 'send', 'cancel', 'approval', 'reconcile'})):
        j(handler, {'error': 'Unknown conversation route'}, status=404)
        return True
    try:
        result = native(action, read_body(handler) if method == 'POST' else None)
        j(handler, result, extra_headers={'Cache-Control': 'no-store'})
    except HTTPError as error:
        try:
            payload = json.load(error)
        except (ValueError, OSError):
            payload = {'error': 'Jaeger gateway rejected the request'}
        j(handler, payload, status=error.code)
    except ValueError as error:
        j(handler, {'error': str(error)}, status=400)
    except (OSError, URLError):
        j(handler, {'error': 'Jaeger is unreachable. Reconnect to observe the existing work; it has not been resubmitted.'}, status=503)
    return True


def project_session(raw, sid, load_messages, limit, before):
    from api.profiles import get_active_profile_name
    if get_active_profile_name() != 'jaeger':
        return raw
    try:
        snapshot = native()
    except (OSError, ValueError):
        # Keep cached history available while explicitly showing loss of sync.
        return {**raw, 'jaeger_sync_error': 'Jaeger is unreachable'}
    if sid != snapshot.get('dispatcher_session'):
        return raw
    messages = [{'id': 'jaeger-' + m['id'], 'role': m['role'], 'content': m['text'],
                 'timestamp': m['ts']} for m in snapshot['messages']]
    end = min(len(messages), before) if before is not None else len(messages)
    start = max(0, end - limit) if limit is not None else 0
    return {**raw, 'messages': messages[start:end] if load_messages else [],
            'message_count': len(messages), '_messages_offset': start,
            '_messages_truncated': bool(start), 'jaeger_revision': snapshot['revision'],
            'regeneration_revision': None, 'tool_calls': []}
