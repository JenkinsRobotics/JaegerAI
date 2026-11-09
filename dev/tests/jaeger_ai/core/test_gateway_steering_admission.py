"""Steering admission is durable before delivery and never replays uncertainty."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading

import pytest

from jaeger_ai.core.gateway import server
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore, RequestConflict, StateConflict


class Request:
    match_info = {'id': 's', 'request_id': 'r'}
    can_read_body = True

    def __init__(self, **body):
        self.body = {'text': 'once', 'steering_id': 'fixed', **body}

    async def json(self):
        return self.body


class Agent:
    def __init__(self):
        self.seen = []

    def steer(self, text):
        self.seen.append(text)
        return True


@pytest.fixture
def app(tmp_path):
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'db.sqlite3'))
    app.store.admit_request('s', 'work', request_id='r')
    app.store.mark_request_status('r', 'running')
    app._active_agents['r'] = Agent()
    return app


def post(app, **body):
    return asyncio.run(app.handle_steer_request(Request(**body)))


def authority():
    return {'lease': None, 'source_file': str(Path(server.__file__).resolve())}


def test_failed_receipt_is_unknown_across_reopen_and_retry(app, monkeypatch):
    append = app.store.append_event
    def fail(session, event, data):
        if event == 'turn.steer':
            raise OSError('private database path')
        return append(session, event, data)
    monkeypatch.setattr(app.store, 'append_event', fail)
    first = post(app)
    assert first.status == 503
    assert 'private database path' not in first.text
    assert app._active_agents['r'].seen == ['once']
    assert app.store.steering_record('s', 'r', 'fixed') is None
    app.store = GatewaySessionStore(app.store.path)
    second = post(app)
    assert second.status == 503
    assert json.loads(second.text)['state'] == 'delivery_unknown'
    assert app._active_agents['r'].seen == ['once']
    assert post(app, text='changed').status == 409
    request = Request()
    request.method = 'GET'
    request.query = {'steering_id': 'fixed'}
    assert asyncio.run(app.handle_steer_request(request)).status == 503


def test_failed_reservation_never_delivers(app, monkeypatch):
    def fail(*a, **k):
        raise OSError('private path')
    monkeypatch.setattr(app.store, 'reserve_steering', fail)
    assert post(app).status == 503
    assert app._active_agents['r'].seen == []


@pytest.mark.parametrize('after', [False, True])
def test_agent_exception_never_replays(app, after):
    agent = app._active_agents['r']
    def fail(text):
        if after:
            agent.seen.append(text)
        raise RuntimeError('private provider information')
    agent.steer = fail
    response = post(app)
    assert response.status == 503
    assert 'private provider' not in response.text
    assert post(app).status == 503
    assert len(agent.seen) == int(after)


def test_interruption_leaves_unknown(app):
    def interrupt(text):
        raise KeyboardInterrupt()
    app._active_agents['r'].steer = interrupt
    with pytest.raises(KeyboardInterrupt):
        post(app)
    assert post(app).status == 503
    assert app.store.steering_admission('s', 'r', 'fixed')['state'] == 'delivery_unknown'


def test_reserved_before_crash_does_not_replay(app):
    assert app.store.reserve_steering('s', 'r', 'fixed', 'once', **authority())
    app.store = GatewaySessionStore(app.store.path)
    assert post(app).status == 503
    assert app._active_agents['r'].seen == []


def test_concurrent_reservations_are_atomic(app):
    gate = threading.Barrier(8)
    def reserve(_):
        store = GatewaySessionStore(app.store.path)
        gate.wait()
        return store.reserve_steering('s', 'r', 'fixed', 'once', **authority())
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(bool(token) for token in pool.map(reserve, range(8))) == 1
    with pytest.raises(RequestConflict):
        app.store.reserve_steering('s', 'r', 'fixed', 'changed', **authority())


def test_dispatch_claim_is_single_use(app):
    token = app.store.reserve_steering('s', 'r', 'fixed', 'once', **authority())
    calls = []
    deliver = lambda: calls.append('once') or True
    assert app.store.deliver_steering('s', 'r', 'fixed', 'once', deliver, producer_token=token, **authority())
    with pytest.raises(StateConflict):
        app.store.deliver_steering('s', 'r', 'fixed', 'once', deliver, producer_token=token, **authority())
    assert calls == ['once']


@pytest.mark.parametrize('mutation', ['cancel', 'identity', 'owner', 'lease', 'source'])
def test_authority_change_after_reservation_blocks_injection(app, mutation):
    lease = app.store.claim_process(source_file=str(Path(server.__file__).resolve()))
    auth = {**authority(), 'lease': lease}
    token = app.store.reserve_steering('s', 'r', 'fixed', 'once', **auth)
    with app.store._immediate() as conn:
        if mutation == 'cancel':
            conn.execute("UPDATE client_requests SET status='cancelling' WHERE request_id='r'")
        elif mutation == 'identity':
            conn.execute("UPDATE client_requests SET digest='changed' WHERE request_id='r'")
        elif mutation == 'owner':
            conn.execute("UPDATE client_requests SET owner_pid=? WHERE request_id='r'", (os.getpid()+1,))
        elif mutation == 'lease':
            conn.execute('UPDATE process_lease SET started_at=started_at+1')
        else:
            conn.execute("UPDATE process_lease SET source_file='other checkout'")
    calls = []
    with pytest.raises(StateConflict):
        app.store.deliver_steering('s', 'r', 'fixed', 'once', lambda: calls.append(1) or True, producer_token=token, **auth)
    assert calls == []


def test_cancellation_scope_blocks_delivery(app):
    app._cancellations.register('r')
    app._cancellations.cancel('r')
    assert post(app).status == 503
    assert app._active_agents['r'].seen == []


def test_rejection_is_durable(app):
    agent = app._active_agents['r']
    def reject(text):
        agent.seen.append(text)
        return False
    agent.steer = reject
    assert post(app).status == 409
    assert post(app).status == 409
    assert agent.seen == ['once']
    assert app.store.steering_admission('s', 'r', 'fixed')['state'] == 'rejected'


def test_legacy_receipt_survives_and_blocks_new_admission(app):
    app.store.append_event('s', 'turn.steer', {'request_id': 'r', 'steering_id': 'fixed', 'text': 'once', 'queued': True})
    assert post(app).status == 200
    assert app._active_agents['r'].seen == []
    assert app.store.reserve_steering('s', 'r', 'fixed', 'once', **authority()) is None
    assert post(app, text='different').status == 409


@pytest.mark.parametrize('body', [{'steering_id': 1}, {'steering_id': []}, {'text': {}}, {'steering_id': 'x'*129}])
def test_invalid_identity_or_payload_does_not_inject(app, body):
    assert post(app, **body).status == 400
    assert app._active_agents['r'].seen == []


def test_new_lease_cannot_dispatch_old_reservation(app):
    lease = app.store.claim_process(source_file=authority()['source_file'])
    token = app.store.reserve_steering('s', 'r', 'fixed', 'once', lease=lease, source_file=authority()['source_file'])
    fresh = app.store.claim_process(source_file=authority()['source_file'])
    calls = []
    with pytest.raises(StateConflict):
        app.store.deliver_steering('s', 'r', 'fixed', 'once', lambda: calls.append(1) or True,
                                  producer_token=token, lease=fresh, source_file=authority()['source_file'])
    assert calls == []


def test_wrong_producer_cannot_dispatch_reservation(app):
    app.store.reserve_steering('s', 'r', 'fixed', 'once', **authority())
    with pytest.raises(StateConflict):
        app.store.deliver_steering('s', 'r', 'fixed', 'once', lambda: True,
                                  producer_token='not-the-producer', **authority())


def test_racing_changed_payload_is_still_conflict(app, monkeypatch):
    reserve = app.store.reserve_steering
    def race(session, request, steering, text, **kwargs):
        reserve(session, request, steering, 'other payload', **kwargs)
        return reserve(session, request, steering, text, **kwargs)
    monkeypatch.setattr(app.store, 'reserve_steering', race)
    assert post(app).status == 409
    assert app._active_agents['r'].seen == []


def test_live_steering_does_not_change_pending_approval(app):
    app.store.mark_request_status('r', 'awaiting_approval')
    assert post(app).status == 200
    assert app.store.get_request('r')['status'] == 'awaiting_approval'
    assert app._active_agents['r'].seen == ['once']


def test_supported_session_deletion_cannot_erase_unknown_delivery(app):
    token = app.store.reserve_steering('s', 'r', 'fixed', 'once', **authority())
    app.store.deliver_steering('s', 'r', 'fixed', 'once', lambda: True,
                              producer_token=token, **authority())
    assert app.store.delete_session('s')
    assert app.store.get_request('r') is None
    app.store = GatewaySessionStore(app.store.path)
    assert app.store.steering_admission('s', 'r', 'fixed')['state'] == 'delivery_unknown'
    app.store.admit_request('s', 'new work', request_id='r')
    app.store.mark_request_status('r', 'running')
    assert post(app).status == 409
    assert app._active_agents['r'].seen == []
    assert post(app, text='different').status == 409
    with pytest.raises(StateConflict):
        app.store.deliver_steering('s', 'r', 'fixed', 'once', lambda: True,
                                  producer_token=token, **authority())


def test_completed_receipt_is_not_attributed_to_recreated_request(app):
    assert post(app).status == 200
    assert app.store.delete_session('s')
    app.store.admit_request('s', 'new work', request_id='r')
    app.store.mark_request_status('r', 'running')
    assert post(app).status == 409
    assert app._active_agents['r'].seen == ['once']


def test_racing_same_payload_retains_uncertain_client_intent(app, monkeypatch):
    reserve = app.store.reserve_steering
    def race(session, request, steering, text, **kwargs):
        reserve(session, request, steering, text, **kwargs)
        return reserve(session, request, steering, text, **kwargs)
    monkeypatch.setattr(app.store, 'reserve_steering', race)
    response = post(app)
    assert response.status == 503
    assert json.loads(response.text)['state'] == 'delivery_unknown'
    assert app._active_agents['r'].seen == []


def test_retained_tombstone_contains_no_request_or_guidance_plaintext(app):
    secret_guidance = 'private follow-up guidance'
    app.store.reserve_steering('s', 'r', 'fixed', secret_guidance, **authority())
    assert app.store.delete_session('s')
    with app.store._get_conn() as conn:
        tombstone = dict(conn.execute('SELECT * FROM steering_admissions').fetchone())
    assert 'text' not in tombstone and 'identity_json' not in tombstone
    assert len(tombstone['text_digest']) == len(tombstone['identity_digest']) == 64
    retained = json.dumps(tombstone)
    assert secret_guidance not in retained
    assert 'input_text' not in retained and 'execution_json' not in retained
    assert 'work' not in tombstone.values()
    app.store.admit_request('s', 'replacement work', request_id='r')
    assert app.store.reserve_steering('s', 'r', 'fixed', secret_guidance, **authority()) is None
    with pytest.raises(RequestConflict):
        app.store.reserve_steering('s', 'r', 'fixed', 'changed guidance', **authority())
