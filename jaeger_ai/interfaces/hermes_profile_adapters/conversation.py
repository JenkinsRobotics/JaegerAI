"""One Dispatcher conversation/control surface for local app and WebUI clients."""
import hashlib
import json
import re
from pathlib import Path

from .native_runs import Run, TERMINAL


def local_connection(layout):
    import yaml
    from jaeger_ai.interfaces.hermes_webui_adapter.bridge_client import BridgeClient
    expected = BridgeClient('jaeger').layout
    if layout is None or layout.root.resolve() != expected.root.resolve():
        raise ValueError('This instance is not connected to the Jaeger WebUI profile')
    config = yaml.safe_load((Path.home() / '.hermes/profiles/jaeger/config.yaml').read_text()) or {}
    base = str(config.get('webui_gateway_base_url') or '').rstrip('/')
    key = str(config.get('webui_gateway_api_key') or '')
    if not base or not key:
        raise ValueError('Configure the Jaeger profile gateway first')
    return {'base_url': base, 'api_key': key, 'instance': expected.root.name}


class Conversation:
    def __init__(self, store, runs, history):
        self.store, self.runs, self.history = store, runs, history
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS conversation_requests ('
                       'id TEXT PRIMARY KEY, digest TEXT NOT NULL)')

    def sessions(self):
        binding = self.store.overview()['dispatcher_session']
        return {'dispatcher', binding} - {None}

    def snapshot(self):
        value = self.history()
        overview = self.store.overview()
        value['dispatcher_session'] = overview['dispatcher_session']
        value['reports'] = overview['reports'][:10]
        run = self.runs.latest(self.sessions())
        value['run'] = self.receipt(run) if run else None
        return value

    @staticmethod
    def receipt(run):
        if isinstance(run, Run):
            with run.condition:
                value = run.snapshot()
                events = list(run.events)
                value["pending_approval_ids"] = [aid for aid, item in run.pending.items() if item["answer"] is None]
        else:
            value = {k: v for k, v in run.items() if k != 'events'}
            events = run.get('events', [])
        terminal = next((e for e in reversed(events) if e.get('event') in {'run.failed', 'run.interrupted'}), {})
        value['error'] = terminal.get('error')
        pending = set(value.get('pending_approval_ids', []))
        value['approvals'] = [e for e in events if e.get('event') == 'approval.request'
                              and e.get('approval_id') in pending]
        value['tools'] = [e for e in events if e.get('event') in {'tool.started', 'tool.completed'}][-8:]
        value['needs_reconciliation'] = value['status'] == 'interrupted' and value.get('execution_unknown', False)
        value['active'] = value['status'] not in TERMINAL or value.get('execution_unknown', False)
        return value

    def start(self, body):
        request_id = body.get('request_id')
        if not isinstance(request_id, str) or not re.fullmatch('[0-9a-f]{32}', request_id):
            raise ValueError('A stable request_id is required')
        payload = {k: body.get(k) for k in ('input', 'model', 'provider', 'workspace')}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT digest FROM conversation_requests WHERE id=?', (request_id,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise ValueError('Request identity was already used for different input')
                return self.receipt(self.runs.get(request_id))
            # Record intent before admission; both interfaces use the same
            # canonical session, while the WebUI binding remains a display ID.
            db.execute('INSERT INTO conversation_requests VALUES (?, ?)', (request_id, digest))
            result = self.runs.start('dispatcher', body.get('input'), body.get('workspace'),
                                     model=body.get('model'), provider=body.get('provider'), run_id=request_id)
        return result

    def control(self, action, body):
        run = self.runs.get(str(body.get('run_id') or ''))
        session = run.session if isinstance(run, Run) else run.get('session_id')
        if session not in self.sessions():
            raise KeyError('Run does not belong to this conversation')
        if action == 'reconcile':
            return self.runs.reconcile(body['run_id'])
        if not isinstance(run, Run):
            raise RuntimeError('Observer restarted; reconcile native execution before controlling this run')
        if action == 'cancel':
            run.cancel()
        elif action == 'approval':
            run.approve(str(body.get('approval_id') or ''), str(body.get('choice') or ''))
        else:
            raise KeyError('Unknown conversation control')
        return self.receipt(run)
