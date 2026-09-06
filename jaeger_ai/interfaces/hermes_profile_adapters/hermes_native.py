"""Authenticated native Hermes Runs client; no CLI replay or transcript copying."""
import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen

from jaeger_ai.core.runtime.agent_workspaces import container_name
from .resilience import ClassifiedError, timeout_setting


def connection():
    raw = subprocess.check_output(
        ['/opt/homebrew/bin/container', 'inspect', container_name('hermes')], timeout=5)
    status = json.loads(raw)[0]['status']
    if status.get('state') != 'running':
        raise ClassifiedError('unavailable', 'Hermes container is not running')
    address = status['networks'][0]['ipv4Address'].split('/')[0]
    path = Path.home() / '.hermes/jaeger-native-api.key'
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ClassifiedError('permission_denied', 'Hermes native credential must be a private regular file')
    key = path.read_text().strip()
    if len(key) < 32:
        raise ClassifiedError('permission_denied', 'Hermes native credential is missing or invalid')
    return f'http://{address}:8645', key


def hermes_turn(run, workspace=None):
    run.execution_unknown = False
    if workspace is not None:
        raise ClassifiedError('unsupported', 'Hermes native workspace override has not been negotiated')
    base, key = connection()
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    def request(path, body=None, timeout=10):
        return urlopen(Request(base + path, headers=headers,
                              data=None if body is None else json.dumps(body).encode()), timeout=timeout)
    if run.cancelled.is_set():
        run.cancel_confirmed = True
        return ''
    # Hermes chooses its run ID. Persist send intent before the request; a lost
    # acceptance response must leave ownership uncertain, never retry the POST.
    run.dispatch(session_id=run.session, run_id=None)
    with request('/v1/runs', {'session_id': run.session, 'input': run.message}) as response:
        accepted = json.load(response)
    native_id = accepted.get('run_id', '')
    if not re.fullmatch(r'run_[0-9a-f]{32}', native_id):
        raise ClassifiedError('invalid_response', 'Hermes returned no valid native run identity')
    run.dispatch(session_id=run.session, run_id=native_id)
    def stop():
        with request(f'/v1/runs/{native_id}/stop', {}) as response:
            response.read()
    run.cancel_native = stop
    if run.cancelled.is_set():
        stop()
    timeout = timeout_setting('HERMES_NATIVE_IDLE_TIMEOUT', 120)
    with request(f'/v1/runs/{native_id}/events', timeout=timeout) as response:
        for raw in response:
            if not raw.startswith(b'data:'):
                continue
            data = raw[5:].strip()
            if data == b'[DONE]':
                break  # DONE without a native terminal event is not success.
            event = json.loads(data)
            kind = event.get('event')
            if event.get('run_id') != native_id:
                raise ClassifiedError('invalid_response', 'Hermes event belongs to another native run')
            if kind == 'message.delta':
                run.emit(kind, delta=str(event.get('delta') or ''))
            elif kind in {'run.started', 'run.queued', 'run.running'}:
                run.emit('native.state', state='queued' if kind == 'run.queued' else 'running')
            elif kind in {'tool.started', 'tool.completed', 'reasoning.available', 'usage'}:
                run.emit(kind, **{k:v for k,v in event.items() if k not in {'event', 'run_id', 'seq'}})
            elif kind == 'approval.request':
                # Preserve a scoped interactive relay for native clients. The
                # legacy Markdown caller denies; it cannot present an approval.
                choices = tuple(c for c in event.get('choices', ['once', 'deny']) if c in {'once', 'deny'})
                if 'deny' not in choices:
                    raise ClassifiedError('invalid_response', 'Native approval cannot be safely denied')
                choice = run.request_approval(event.get('description') or event.get('command') or 'Hermes tool approval', choices=choices)
                with request(f'/v1/runs/{native_id}/approval', {'choice': choice, 'all': False}) as answer:
                    answer.read()
            elif kind == 'run.completed':
                run.execution_unknown = False
                return event.get('output') if isinstance(event.get('output'), str) else run.output
            elif kind == 'run.cancelled':
                run.execution_unknown = False
                run.cancel_confirmed = True
                return run.output
            elif kind == 'run.failed':
                run.execution_unknown = False
                raise ClassifiedError('native_error', str(event.get('error') or 'Hermes native run failed'))
    raise ClassifiedError('incomplete_stream', 'Hermes stream ended without a native terminal result; inspect the native run before retrying')
