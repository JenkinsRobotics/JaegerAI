"""Resident inner-run checkpoints are never bridge request receipts.

No provider, sockets, or fabricated resident terminal rows: exercise the actual
TurnExecutive producer and restart recovery against disposable SQLite stores.
"""
import json
from types import SimpleNamespace

import pytest
from jaeger_agent.cognition.executive import TurnExecutive
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.memory import sqlite_store

from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.runtime.native_turns import NativeTurns


class ScriptedLoop:
    primary_adapter = SimpleNamespace(name='isolated-scripted-loop')
    run_id = None
    last_iteration_count = 1

    def __init__(self, halt):
        self.last_halt_reason = halt
        self.calls = 0
        self.messages = []

    def bind_run(self, run_id):
        self.run_id = run_id

    def run_turn(self, text):
        self.calls += 1
        self.messages.append({'role': 'assistant', 'content': 'inner output'})
        return 'inner output'


class Request(dict):
    can_read_body = True

    def __init__(self, **body):
        super().__init__()
        self.match_info = {'id': 's'}
        self.body = {'request_id': 'r', **body}

    async def json(self):
        return self.body


@pytest.mark.asyncio
@pytest.mark.parametrize('halt,expected', [(None, 'completed'), ('interrupted', 'cancelled'), ('complete_task', 'active')])
@pytest.mark.parametrize('bridge_collision', [False, True])
async def test_real_resident_producer_never_consumes_bridge_proof(tmp_path, monkeypatch, halt, expected, bridge_collision):
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    try:
        loop = ScriptedLoop(halt)
        runs = SqliteRunStore()
        executive = TurnExecutive(loop, runs, SqliteCommitmentStore(), provider='scripted')
        path = tmp_path / 'gateway.sqlite3'
        store = GatewaySessionStore(path)
        store.admit_request('s', 'test', request_id='r')
        native_session = f'{OWNER_RUN_SESSION_PREFIX}s'
        run = executive.ensure_run()
        store.bind_native('r', native_run_id=run.id, native_session=native_session)
        assert executive.run_turn('test') == 'inner output'
        assert runs.get(run.id).state == expected
        assert runs.latest_checkpoint(run.id).cursor['messages'][-1]['content'] == 'inner output'
        if bridge_collision:
            # A valid bridge receipt with matching strings is still the wrong
            # producer. It must not become resident success or release a queue.
            bridge = NativeTurns(tmp_path / 'run')
            bridge.accept(run.id, native_session)
            bridge.finish(run.id, native_session, {'text': 'unrelated bridge answer'})
        store.enqueue_request('s', 'next', request_id='next')
        app = JaegerGatewayApp(store=GatewaySessionStore(path))
        app.store.recover_interrupted_sessions()
        monkeypatch.setattr(app, '_instance_root', lambda: tmp_path)
        starts = []
        monkeypatch.setattr(app, '_start_admitted_turn', lambda row, *args: starts.append(row))
        response = await app.handle_reconcile(Request())
        data = json.loads(response.text)
        assert response.status == 409
        assert data['status'] == 'execution_unknown'
        assert data['receipt']['error'] == 'owner_request_receipt_unavailable'
        assert data['receipt']['source'] == 'resident_owner'
        assert data['receipt']['execution_unknown'] is True
        assert data['receipt']['turn_id'] == run.id
        assert data['receipt']['session_id'] == native_session
        assert not data['reconciled']
        assert loop.calls == 1 and starts == []
        assert app.store.get_request('next')['status'] == 'queued'
        assert not [m for m in app.store.get_session('s')['messages'] if m['role'] == 'assistant']
        assert (tmp_path / 'run' / 'native-turns.sqlite3').exists() is bridge_collision
        acknowledged = json.loads((await app.handle_reconcile(Request(acknowledge_unknown=True))).text)
        assert acknowledged['outcome'] == 'unknown_not_replayed'
        assert acknowledged['status'] == 'execution_unknown'
        assert loop.calls == 1 and starts == []
    finally:
        sqlite_store.close()


def test_owner_lookup_does_not_open_any_bridge_store(tmp_path, monkeypatch):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'gateway.sqlite3'))

    def forbidden_root():
        pytest.fail('Resident reconciliation must not resolve the bridge store')

    monkeypatch.setattr(app, '_instance_root', forbidden_root)
    assert app._native_receipt('run', f'{OWNER_RUN_SESSION_PREFIX}s')['error'] == 'owner_request_receipt_unavailable'


def test_bridge_terminal_receipt_remains_supported(tmp_path, monkeypatch):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'gateway.sqlite3'))
    monkeypatch.setattr(app, '_instance_root', lambda: tmp_path)
    bridge = NativeTurns(tmp_path / 'run')
    bridge.accept('run', 'bridge-session')
    bridge.finish('run', 'bridge-session', {'text': 'bridge answer'})
    receipt = app._native_receipt('run', 'bridge-session')
    assert receipt['source'] == 'native_bridge_receipt'
    assert receipt['status'] == 'completed' and receipt['execution_unknown'] is False
    assert receipt['reply']['text'] == 'bridge answer'
    assert app._native_receipt(None, 'bridge-session') is None
    assert app._native_receipt('run', None) is None
