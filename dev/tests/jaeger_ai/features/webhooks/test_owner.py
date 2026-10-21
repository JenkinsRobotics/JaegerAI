"""Real isolated SQLite/registry/task/approval owners; no model or external ingress."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml
from jaeger_ai.features.webhooks import owner


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    layout = InstanceLayout(root=tmp_path/'instance')
    layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(instance_name='webhook-fixture', model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR', str(layout.root))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    app.store.ensure_session('webhook-owned-home', workspace=str(tmp_path), metadata={'agent_id': 'native:builder'})
    return app


def definition(**changes):
    return {'name': 'Owned fixture', 'provider': 'generic', 'events': ['changed'], 'senders': ['owned-sender'],
            'session_id': 'webhook-owned-home', 'objective': 'Review this fixture event; use existing policy.',
            'enabled': False, 'archived': False, **changes}


def setup(app, sid='owned-a'):
    first = owner.save(app, sid, {'operation_id': 'create-' + sid, 'expected_revision': 0, 'definition': definition()}, 'owner:webui')
    assert first['subscription']['enabled'] is False
    return owner.save(app, sid, {'operation_id': 'enable-' + sid, 'expected_revision': 1, 'definition': definition(enabled=True)}, 'owner:webui')['subscription']


def event(sid='owned-a', eid='owned-event', **changes):
    return {'subscription_id': sid, 'provider': 'generic', 'delivery_id': eid, 'event_type': 'changed',
            'sender': 'owned-sender', 'title': 'Owned event', 'prompt': 'Private fixture content', 'authenticated': True, **changes}


def test_subscription_dedupe_scope_filters_out_of_order_and_reopen(gateway):
    setup(gateway)
    setup(gateway, 'owned-b')
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: owner.receive(gateway, event()), range(2)))
    assert receipts[0]['task_id'] == receipts[1]['task_id']
    assert sum(bool(r['replayed']) for r in receipts) == 1
    assert len(gateway.task_owner.store.list_tasks()) == 1
    # Same provider identity is distinct only in a different saved subscription.
    other = owner.receive(gateway, event('owned-b'))
    assert other['task_id'] != receipts[0]['task_id']
    older = owner.receive(gateway, event(eid='older-event'))
    assert older['ok']  # arrival history, no invented remote chronology
    assert owner.receive(gateway, event(prompt='Changed content'))['status'] == 'conflict'
    for changes, reason in [({'sender': 'unauthorized'}, 'sender_filter_rejected'), ({'event_type': 'other'}, 'event_filter_rejected'), ({'authenticated': False}, 'shared_secret_required')]:
        denied = owner.receive(gateway, event(eid='reject-' + reason, **changes))
        assert denied['status'] == 'rejected' and denied['reason'] == reason
    assert len(gateway.task_owner.store.list_tasks()) == 3
    assert len(gateway.store.list_pending_approvals()) == 3
    assert gateway.store.list_requests() == []  # ingress never runs a model/tool
    rows = owner.history(gateway, 'owned-a')['deliveries']
    assert 'Private fixture content' not in json.dumps(rows)
    assert 'owned-sender' not in json.dumps(rows)
    assert [r['received_at'] for r in rows] == sorted((r['received_at'] for r in rows), reverse=True)
    gateway.store = GatewaySessionStore(gateway.store.path)
    replay = owner.receive(gateway, event())
    assert replay['replayed'] and replay['task_id'] == receipts[0]['task_id']
    task = gateway.task_owner.store.get_task(replay['task_id'])
    assert task.provenance['authorized'] is False
    assert task.agent_id == 'native:builder'
    assert task.payload['execution']['caller'] == 'owner:webui'
    assert 'Untrusted inbound webhook data' in task.goal
    assert 'allowed_tools' not in task.payload['execution']


def test_atomic_admission_rollback_and_response_loss(gateway, monkeypatch):
    setup(gateway)
    create_approval = gateway.store.create_approval
    def crash_after_insert(**kwargs):
        create_approval(**kwargs)
        raise RuntimeError('Owned injected failure before commit')
    with monkeypatch.context() as patch:
        patch.setattr(gateway.store, 'create_approval', crash_after_insert)
        with pytest.raises(RuntimeError):
            owner.receive(gateway, event())
    assert gateway.task_owner.store.list_tasks() == []
    assert gateway.store.list_pending_approvals() == []
    assert owner.history(gateway, 'owned-a')['deliveries'] == []
    # A post-commit lost response cannot create a second task or approval.
    with monkeypatch.context() as patch:
        patch.setattr(gateway.event_bus, 'publish', lambda *a: (_ for _ in ()).throw(RuntimeError('Owned lost response')))
        with pytest.raises(RuntimeError):
            owner.receive(gateway, event())
    receipt = owner.receive(gateway, event())
    assert receipt['replayed']
    assert len(gateway.task_owner.store.list_tasks()) == 1
    assert len(gateway.store.list_pending_approvals()) == 1
    assert owner.history(gateway, 'owned-a')['deliveries'][0]['approval_id'] == receipt['approval_id']
    assert gateway.store.list_requests() == []


@pytest.mark.asyncio
async def test_owner_routes_denial_revoke_and_unknown_do_not_dispatch(gateway):
    setup(gateway)
    first = owner.receive(gateway, event())
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        rejected = await client.post('/v1/approvals/' + first['approval_id'], json={'approved': False, 'decision': 'deny'})
        assert rejected.status == 200
        assert gateway.task_owner.store.get_task(first['task_id']).state.value == 'cancelled'
        assert owner.receive(gateway, event())['task_id'] == first['task_id']
        assert gateway.store.list_pending_approvals() == []
        denied_history = owner.history(gateway, 'owned-a')['deliveries'][0]
        assert denied_history['status'] == 'cancelled' and denied_history['admission_status'] == 'awaiting_approval'
        second = owner.receive(gateway, event(eid='second-owned'))
        approved = await client.post('/v1/approvals/' + second['approval_id'], json={'approved': True, 'decision': 'once'})
        assert approved.status == 200
        owner.save(gateway, 'owned-a', {'operation_id': 'disable-owned', 'expected_revision': 2, 'definition': definition()}, 'owner:webui')
        gateway._start_admitted_turn = lambda *a: pytest.fail('revoked task dispatched')
        await gateway.task_owner._execute(second['task_id'])
        task = gateway.task_owner.store.get_task(second['task_id'])
        assert task.state.value == 'paused' and 'revoked or changed' in task.error
        assert gateway.store.list_requests() == []
        # Existing unknown receipts stay intact even after revocation/approval.
        child = 'task:' + task.task_id
        gateway.store.ensure_session(child, metadata={'agent_id': 'native:builder', 'task_id': task.task_id})
        gateway.store.admit_request(child, 'Previously admitted fixture', request_id=task.task_id + ':0')
        gateway.store.complete_request(task.task_id + ':0', status='execution_unknown', result={'error': 'Retained uncertainty'})
        before = gateway.store.get_request(task.task_id + ':0')
        await gateway.task_owner._execute(task.task_id)
        assert gateway.store.get_request(task.task_id + ':0') == before
        rows = await (await client.get('/v1/webhooks/owned-a/deliveries')).json()
        assert any(r.get('request_status') == 'execution_unknown' for r in rows['deliveries'])
        assert owner.receive(gateway, event(eid='after-revoke'))['reason'] == 'subscription_disabled_or_missing'
    async with TestClient(TestServer(gateway.app), headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/webhooks')).status == 403
        assert (await client.post('/v1/webhooks/nope', json={})).status == 403
    async with TestClient(TestServer(gateway.app), headers=client_headers('jaegerd')) as client:
        assert (await client.get('/v1/webhooks')).status == 200
        assert (await client.post('/v1/webhooks/owned-a', json={})).status == 403


def test_subscription_cas_archive_restore_and_blocked_admission(gateway):
    setup(gateway)
    stale = owner.save(gateway, 'owned-a', {'operation_id': 'stale-owned', 'expected_revision': 1, 'definition': definition()}, 'owner:webui')
    assert not stale['ok'] and stale['http_status'] == 409
    archived = owner.save(gateway, 'owned-a', {'operation_id': 'archive-owned', 'expected_revision': 2, 'definition': definition(archived=True)}, 'owner:webui')
    assert archived['subscription']['archived'] and not archived['subscription']['enabled']
    with pytest.raises(ValueError, match='Restore must remain disabled'):
        owner.save(gateway, 'owned-a', {'operation_id': 'unsafe-restore', 'expected_revision': 3, 'definition': definition(enabled=True)}, 'owner:webui')
    restored = owner.save(gateway, 'owned-a', {'operation_id': 'restore-owned', 'expected_revision': 3, 'definition': definition()}, 'owner:webui')
    assert restored['subscription']['revision'] == 4 and not restored['subscription']['enabled']
    assert owner.receive(gateway, event(), blocked=True)['reason'] == 'admission_stopped'
    assert gateway.task_owner.store.list_tasks() == []


def test_revocation_between_precheck_and_final_admission_is_refused(gateway, monkeypatch):
    setup(gateway)
    receipt = owner.receive(gateway, event())
    gateway.task_owner.resolve(receipt['task_id'], True)
    admit = gateway.store.admit_request
    def revoke_then_admit(*args, **kwargs):
        owner.save(gateway, 'owned-a', {'operation_id': 'race-disable', 'expected_revision': 2, 'definition': definition()}, 'owner:webui')
        return admit(*args, **kwargs)
    monkeypatch.setattr(gateway.store, 'admit_request', revoke_then_admit)
    gateway._start_admitted_turn = lambda *a: pytest.fail('revoked after precheck still dispatched')
    asyncio.run(gateway.task_owner._execute(receipt['task_id']))
    assert gateway.store.list_requests() == []
    assert 'before admission' in gateway.task_owner.store.get_task(receipt['task_id']).error


def test_approved_proposal_uses_normal_admitted_dispatch_once(gateway):
    setup(gateway)
    receipt = owner.receive(gateway, event())
    assert gateway.store.list_requests() == []
    gateway.task_owner.resolve(receipt['task_id'], True)
    calls = []
    def dispatch(admitted, sid, prompt):
        calls.append(admitted)
        assert gateway.store.get_session(sid)['metadata']['agent_id'] == 'native:builder'
        assert 'Untrusted inbound webhook data' in prompt
        gateway.store.complete_request(admitted['request_id'], status='completed', result={'output': {'review': 'Synthetic boundary result'}})
    gateway._start_admitted_turn = dispatch
    asyncio.run(gateway.task_owner._execute(receipt['task_id']))
    assert len(calls) == 1
    assert calls[0]['execution']['caller'] == 'owner:webui'
    assert calls[0]['execution']['is_subordinate'] is True
    assert gateway.task_owner.store.get_task(receipt['task_id']).state.value != 'completed_verified'
    assert owner.receive(gateway, event())['task_id'] == receipt['task_id']
    assert len(gateway.store.list_requests()) == 1


@pytest.mark.asyncio
async def test_loopback_transport_to_gateway_sink_commits_one_approval_proposal(gateway):
    from urllib.request import Request, urlopen

    from jaeger_ai.core.runtime.background_producers import BackgroundProducers
    from jaeger_ai.core.runtime.webhooks import serve
    gateway._loop = asyncio.get_running_loop()
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        created = await client.post('/v1/webhooks/owned-a', json={'operation_id': 'http-create', 'expected_revision': 0, 'definition': definition()})
        assert created.status == 200 and not (await created.json())['subscription']['enabled']
        enabled = await client.post('/v1/webhooks/owned-a', json={'operation_id': 'http-enable', 'expected_revision': 1, 'definition': definition(enabled=True)})
        assert enabled.status == 200
        producers = BackgroundProducers(None, gateway._background_sink(), display_name='Owned fixture')
        producers._accepting = True
        server = serve(producers._handle_webhook, port=0, secret='owned-memory-only-secret')
        def send():
            request = Request(f'http://127.0.0.1:{server.server_port}/hook/owned-a',
                data=json.dumps({'sender': 'owned-sender', 'delivery_id': 'http-fixture-event', 'action': 'turn', 'prompt': 'Fixture data owned-memory-only-secret'}).encode(),
                headers={'Authorization': 'Bearer owned-memory-only-secret', 'X-Jaeger-Event': 'changed'})
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read())
        try:
            first = await asyncio.to_thread(send)
            second = await asyncio.to_thread(send)
            assert first['status'] == 'awaiting_approval'
            assert second['replayed'] and second['task_id'] == first['task_id']
            assert gateway.store.list_requests() == []
            assert len(gateway.store.list_pending_approvals()) == 1
            task = gateway.task_owner.store.get_task(first['task_id'])
            assert task.state.value == 'paused' and task.provenance['authorized'] is False
            assert 'owned-memory-only-secret' not in task.goal
            history = await (await client.get('/v1/webhooks/owned-a/deliveries')).json()
            assert len(history['deliveries']) == 1
            assert history['deliveries'][0]['approval_id'] == first['approval_id']
            assert 'webhook.changed' in __import__('jaeger_ai.core.gateway.event_bus', fromlist=['EVENT_TYPES']).EVENT_TYPES
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            producers._accepting = False
            gateway._loop = None
