"""Confirmed reconciliation releases queued work; no servers or provider calls."""
import json
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.server import JaegerGatewayApp, _authenticate_caller
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class Request(dict):
    can_read_body = True
    method = 'POST'
    path = '/v1/sessions/s/reconcile'
    headers = {}

    def __init__(self, session='s', request_id='active', **body):
        super().__init__()
        self.match_info = {'id': session}
        self.body = {'request_id': request_id, **body}

    async def json(self):
        return self.body


@pytest.fixture
def recovered(tmp_path, monkeypatch):
    path = tmp_path / 'sessions.sqlite3'
    store = GatewaySessionStore(path)
    store.admit_request('s', 'original work', request_id='active')
    store.bind_native('active', native_run_id='native', native_session='native-session')
    store.enqueue_request('s', 'paused work', request_id='paused')
    store.update_queue_item('s', 'paused', status='paused')
    store.enqueue_request('s', 'next work', request_id='next', requested={'allowed_tools': []})
    store.enqueue_request('s', 'last work', request_id='last')
    app = JaegerGatewayApp(store=GatewaySessionStore(path))
    started = []
    monkeypatch.setattr(app, '_start_admitted_turn', lambda row, *args: started.append(row))
    app.store.recover_interrupted_sessions()
    app._drain_all_queues()
    assert started == []
    return SimpleNamespace(app=app, started=started)


def receipt(status):
    return {'status': status, 'execution_unknown': False, 'reply': {'text': 'native result'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
async def test_confirmed_reconciliation_drains_once_preserving_receipt_and_pause(recovered, monkeypatch, status):
    app = recovered.app
    frozen = app.store.get_request('next')['execution']
    native = receipt(status)
    lookups = []
    def read(run, session):
        lookups.append((run, session))
        return native
    monkeypatch.setattr(app, '_native_receipt', read)
    response = await app.handle_reconcile(Request())
    payload = json.loads(response.text)
    assert response.status == 200 and payload['reconciled']
    assert payload['status'] == status
    assert payload['result']['backend'] == 'native_receipt'
    assert payload['result']['reconciliation'] == native
    assert lookups == [('native', 'native-session')]
    assert [row['request_id'] for row in recovered.started] == ['next']
    assert recovered.started[0]['execution'] == frozen
    assert app.store.get_session('s')['status'] == 'running'
    assert [(row['request_id'], row['status']) for row in app.store.list_queue('s')] == [('paused', 'paused'), ('last', 'queued')]
    events = app.event_bus.get_replay_events('s')
    terminal = [e for e in events if e.event == 'turn.reconciled']
    assert len(terminal) == 1 and terminal[0].data['status'] == status
    assert not any(e.event in {'turn.finish', 'turn.failed', 'turn.cancelled'} for e in events)
    assert len([m for m in app.store.get_session('s')['messages'] if m['role'] == 'assistant']) == 1
    repeated = json.loads((await app.handle_reconcile(Request())).text)
    assert repeated['already_terminal'] and not repeated['reconciled']
    assert len(recovered.started) == 1 and len(lookups) == 1
    assert len(app.event_bus.get_replay_events('s')) == len(events)


@pytest.mark.asyncio
@pytest.mark.parametrize('native', [None, {'execution_unknown': True, 'status': 'completed'}, receipt('running'), receipt('awaiting_approval')])
async def test_unresolved_receipt_never_drains(recovered, monkeypatch, native):
    monkeypatch.setattr(recovered.app, '_native_receipt', lambda *a: native)
    response = await recovered.app.handle_reconcile(Request())
    assert response.status == 409
    assert recovered.started == []
    assert recovered.app.store.get_session('s')['status'] == 'execution_unknown'
    assert recovered.app.store.get_request('next')['status'] == 'queued'


@pytest.mark.asyncio
async def test_acknowledgement_only_keeps_existing_no_drain_semantics(recovered, monkeypatch):
    monkeypatch.setattr(recovered.app, '_native_receipt', lambda *a: None)
    response = await recovered.app.handle_reconcile(Request(acknowledge_unknown=True))
    assert response.status == 200
    assert recovered.started == []
    assert recovered.app.store.get_request('active')['status'] == 'execution_unknown'
    assert recovered.app.store.get_request('next')['status'] == 'queued'


@pytest.mark.asyncio
async def test_confirmed_reconciliation_does_not_unpause_work(recovered, monkeypatch):
    app = recovered.app
    for rid in ('next', 'last'):
        app.store.update_queue_item('s', rid, status='paused')
    monkeypatch.setattr(app, '_native_receipt', lambda *a: receipt('completed'))
    assert (await app.handle_reconcile(Request())).status == 200
    assert recovered.started == []
    assert all(row['status'] == 'paused' for row in app.store.list_queue('s'))


@pytest.mark.asyncio
async def test_historical_reconciliation_does_not_dispatch_beside_newer_work(recovered, monkeypatch):
    app = recovered.app
    app.store.acknowledge_unknown('s', actor='owner', request_id='active')
    app.store.admit_request('s', 'new work', request_id='newer')
    monkeypatch.setattr(app, '_native_receipt', lambda *a: receipt('completed'))
    assert (await app.handle_reconcile(Request())).status == 200
    assert recovered.started == []
    assert app.store.get_request('newer')['status'] == 'admitted'
    assert app.store.get_request('next')['status'] == 'queued'


@pytest.mark.asyncio
@pytest.mark.parametrize('session,rid', [('other', 'active'), ('s', 'missing')])
async def test_wrong_session_or_request_cannot_settle_or_drain(recovered, monkeypatch, session, rid):
    def forbidden(*a): pytest.fail('Identity rejection must precede receipt lookup')
    monkeypatch.setattr(recovered.app, '_native_receipt', forbidden)
    response = await recovered.app.handle_reconcile(Request(session, rid))
    assert response.status == 404 and recovered.started == []
    assert recovered.app.store.get_request('active')['status'] == 'execution_unknown'


@pytest.mark.parametrize('state', ['admitted', 'running', 'awaiting_approval', 'cancelling'])
def test_late_completion_cannot_release_newer_busy_session(recovered, state):
    from jaeger_ai.core.gateway.session_store import RequestBusy
    store = recovered.app.store
    store.acknowledge_unknown('s', actor='owner', request_id='active')
    store.admit_request('s', 'new work', request_id='newer')
    store.mark_request_status('newer', state)
    store.update_status('s', 'cancelling' if state == 'cancelling' else 'running')
    store.complete_request('active', status='completed', result={'output': 'late result'})
    assert store.get_session('s')['status'] == ('cancelling' if state == 'cancelling' else 'running')
    with pytest.raises(RequestBusy):
        store.admit_request('s', 'must not overlap', request_id='overlap')
    assert store.promote_next_queue_item('s') is None


def test_late_completion_preserves_newer_unacknowledged_unknown(recovered):
    store = recovered.app.store
    store.acknowledge_unknown('s', actor='owner', request_id='active')
    store.admit_request('s', 'new work', request_id='newer')
    store.recover_interrupted_sessions()
    store.complete_request('active', status='completed', result={})
    assert store.get_session('s')['status'] == 'execution_unknown'
    assert store.promote_next_queue_item('s') is None


@pytest.mark.parametrize('iteration', range(5))
def test_concurrent_old_settlement_and_new_admission_preserve_busy_owner(recovered, iteration):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store = recovered.app.store
    store.acknowledge_unknown('s', actor='owner', request_id='active')
    barrier = Barrier(2)
    def settle():
        barrier.wait()
        return GatewaySessionStore(store.path).complete_request('active', status='completed', result={})
    def admit():
        barrier.wait()
        return GatewaySessionStore(store.path).admit_request('s', 'new work', request_id='newer')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(settle), pool.submit(admit)
        assert first.result()['status'] == 'completed'
        assert second.result()['accepted']
    assert store.get_session('s')['status'] == 'running'
    assert store.promote_next_queue_item('s') is None


@pytest.mark.asyncio
async def test_concurrent_reconciliation_has_one_terminal_event_and_dispatch(recovered, monkeypatch):
    import asyncio
    app = recovered.app
    monkeypatch.setattr(app, '_native_receipt', lambda *a: receipt('completed'))
    responses = await asyncio.gather(app.handle_reconcile(Request()), app.handle_reconcile(Request()))
    assert all(r.status == 200 for r in responses)
    assert sum(json.loads(r.text)['reconciled'] for r in responses) == 1
    assert [r['request_id'] for r in recovered.started] == ['next']
    assert len([e for e in app.event_bus.get_replay_events('s') if e.event == 'turn.reconciled']) == 1


@pytest.mark.asyncio
async def test_closed_client_and_failing_observer_do_not_block_drain(recovered, monkeypatch):
    import asyncio
    app = recovered.app
    dead = asyncio.new_event_loop(); dead.close()
    app.event_bus._subscribers[asyncio.Event()] = ('s', dead)
    def broken(event): raise RuntimeError('disconnected observer')
    app.event_bus.add_observer(broken)
    monkeypatch.setattr(app, '_native_receipt', lambda *a: receipt('completed'))
    assert (await app.handle_reconcile(Request())).status == 200
    assert [r['request_id'] for r in recovered.started] == ['next']
    assert not app.event_bus._subscribers


@pytest.mark.asyncio
@pytest.mark.parametrize('caller,stopped,expected', [(None, False, 401), ('mcp', False, 403), ('cli', True, 423)])
async def test_authentication_and_stop_deny_before_reconciliation(recovered, monkeypatch, caller, stopped, expected):
    from jaeger_ai.core.gateway import server, caller_auth
    from jaeger_ai.core.gateway.global_stop import GlobalStop
    request = Request()
    request.app = {server.CALLER_AUTH_KEY: {'auth': SimpleNamespace(authenticate=lambda value: caller_auth.CALLERS.get(caller))}}
    monkeypatch.setattr(server, '_route_template', lambda request: '/v1/sessions/{id}/reconcile')
    monkeypatch.setattr(GlobalStop, 'load', classmethod(lambda cls: SimpleNamespace(engaged=lambda: stopped)))
    def forbidden(*a): pytest.fail('Denied caller must not read receipt')
    monkeypatch.setattr(recovered.app, '_native_receipt', forbidden)
    response = await _authenticate_caller(request, recovered.app.handle_reconcile)
    assert response.status == expected
    assert recovered.started == []
    assert recovered.app.store.get_request('active')['status'] == 'execution_unknown'


def test_acknowledged_unknown_history_does_not_block_current_settlement(recovered):
    store = recovered.app.store
    store.acknowledge_unknown('s', actor='owner', request_id='active')
    store.admit_request('s', 'new work', request_id='newer')
    store.complete_request('newer', status='completed', result={})
    assert store.get_request('active')['status'] == 'execution_unknown'
    assert store.get_session('s')['status'] == 'idle'
    assert store.promote_next_queue_item('s')['request_id'] == 'next'


def test_concurrent_same_receipt_settlement_is_durable_once(recovered):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store = recovered.app.store
    barrier = Barrier(2)
    def settle():
        barrier.wait()
        return GatewaySessionStore(store.path).complete_request(
            'active', status='completed', result={'backend': 'native_receipt'},
            assistant_text='one reply', event_name='turn.reconciled')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(settle), pool.submit(settle)
        results = [first.result(), second.result()]
    assert sorted(row['replayed'] for row in results) == [False, True]
    assert len([m for m in store.get_session('s')['messages'] if m['role'] == 'assistant']) == 1
    assert len([e for e in store.replay_events('s')['events'] if e['event'] == 'turn.reconciled']) == 1


@pytest.mark.parametrize('latest_status,session_status', [('completed', 'idle'), ('failed', 'failed'), ('cancelled', 'idle')])
@pytest.mark.parametrize('old_status', ['completed', 'failed', 'cancelled'])
def test_latest_terminal_session_truth_survives_historical_receipt(recovered, latest_status, session_status, old_status):
    store = recovered.app.store
    store.acknowledge_unknown('s', actor='owner', request_id='active')
    store.admit_request('s', 'new work', request_id='newer')
    store.complete_request('newer', status=latest_status, result={'source': 'newer'}, session_status=session_status)
    store.complete_request('active', status=old_status, result={'source': 'historical'})
    assert store.get_request('active')['status'] == old_status
    assert store.get_request('newer')['result'] == {'source': 'newer'}
    assert store.get_session('s')['status'] == session_status
    # A replay of the old receipt also cannot mutate the session projection.
    assert store.complete_request('active', status=old_status, result={})['replayed']
    assert store.get_session('s')['status'] == session_status


@pytest.mark.parametrize('status,session_status', [('completed', 'idle'), ('failed', 'failed'), ('cancelled', 'idle')])
def test_queue_promotion_owns_status_by_admission_not_creation(recovered, status, session_status):
    store = recovered.app.store
    store.acknowledge_unknown('s', actor='owner', request_id='active')
    store.admit_request('s', 'created after queued item', request_id='newer')
    store.recover_interrupted_sessions()
    store.acknowledge_unknown('s', actor='owner', request_id='newer')
    assert store.get_request('next')['created_at'] < store.get_request('newer')['created_at']
    assert store.promote_next_queue_item('s')['request_id'] == 'next'
    store.complete_request('next', status=status, result={}, session_status=session_status)
    assert store.get_session('s')['status'] == session_status
    store.complete_request('newer', status='failed' if status != 'failed' else 'completed', result={})
    assert store.get_session('s')['status'] == session_status


def test_durable_admission_history_survives_replay_event_removal(recovered):
    store = recovered.app.store
    # Simulate bounded replay retention; authoritative history is unpruned.
    with store._immediate() as conn:
        conn.execute('DELETE FROM events')
    store.complete_request('active', status='completed', result={})
    assert store.get_session('s')['status'] == 'idle'
    assert store.promote_next_queue_item('s')['request_id'] == 'next'


@pytest.mark.parametrize('missing', [True, False])
def test_missing_or_mismatched_admission_proof_preserves_historical_session(recovered, missing):
    store = recovered.app.store
    with store._immediate() as conn:
        if missing:
            conn.execute("DELETE FROM activity_history WHERE event='turn.start'")
        else:
            conn.execute("UPDATE activity_history SET data_json=json_set(data_json, '$.turn_id', 'wrong-turn') WHERE event='turn.start'")
    store.complete_request('active', status='completed', result={'output': 'attested outcome'})
    assert store.get_request('active')['status'] == 'completed'
    assert store.get_session('s')['status'] == 'execution_unknown'
    assert store.promote_next_queue_item('s') is None


@pytest.mark.asyncio
async def test_review_completed_native_receipt_preserves_accounting(recovered, monkeypatch, tmp_path):
    from jaeger_ai.core.runtime.native_turns import NativeTurns
    native=NativeTurns(tmp_path/'run')
    native.accept('native','native-session')
    usage={'prompt_tokens':12, 'completion_tokens':8, 'total_tokens':20}
    reply={'text':'Completed diagnostic report', 'halt_reason':'complete_task',
           'usage':usage, 'metadata':{'author':'test-worker', 'tool_count':2},
           'diagnostics': {'error':'401 api_key=dummy-nested-secret'}}
    native.finish('native','native-session',reply)
    monkeypatch.setattr(recovered.app,'_instance_root',lambda:tmp_path)
    response=await recovered.app.handle_reconcile(Request())
    payload=json.loads(response.text)
    assert response.status==200 and payload['status']=='completed'
    exposed=payload['result']['reconciliation']['reply']
    assert exposed['usage']==usage
    assert exposed['metadata']==reply['metadata']
    assert exposed['text']==reply['text']
    assert 'dummy-nested-secret' not in json.dumps(payload)
    assert native.get('native','native-session')['reply']==reply
    assert [row['request_id'] for row in recovered.started]==['next']
