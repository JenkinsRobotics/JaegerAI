"""Owned local finance metadata fixtures. No keys, providers or payment adapters."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml
from jaeger_ai.features.finance import review
from jaeger_ai.features.finance.approval import ApprovalEngine, PolicyViolationError
from jaeger_ai.features.finance.audit import AuditLog
from jaeger_ai.features.finance.models import ApprovalTier, PendingAction
from jaeger_ai.features.finance.security import FinanceCipher
from jaeger_ai.features.finance.store import FinanceStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('JAEGER_HOME', str(tmp_path))
    layout = InstanceLayout(root=tmp_path/'instance'); layout.ensure_dirs()
    dump_yaml(layout.config_path, Config(instance_name='finance-fixture', model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR', str(layout.root))
    app = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    return tmp_path, app


def existing(root):
    return FinanceStore(db_path=root/'finance/finance.db', cipher=FinanceCipher(key=b'\x01'*32))


def action(store, aid='act_000000000001', *, kind='categorize_merchant', payload=None, status='pending', expires=None):
    row = PendingAction(aid, kind, payload or {'merchant':'Owned Cafe','category':'Dining'}, 'Private rationale withheld',
                        ApprovalTier.ONE_CLICK, expires_at=expires or (datetime.now(UTC)+timedelta(hours=1)).isoformat(), status=status)
    store.record_pending_action(row)
    return row


def test_closed_policy_has_no_purchase_or_implicit_operation_authority(setup):
    root, _ = setup; store = existing(root); engine = ApprovalEngine(store)
    for name in ('purchase', 'charge_card', 'make_payment', 'transfer_money', 'trade', 'read_accounts_then_make_payment', 'invented'):
        assert engine.evaluate_operation(name) == ApprovalTier.BLOCKED
        with pytest.raises(PolicyViolationError): engine.stage_action(name, {'amount':4,'currency':'USD','merchant':'Owned'}, 'Fixture')
    assert store.get_pending_actions() == []
    assert review.policy()['execution_supported'] is False
    assert review.policy()['provider'] == 'not_probed'


@pytest.mark.asyncio
async def test_status_never_initializes_keys_or_store_and_denies_readonly_caller(setup, monkeypatch):
    root, app = setup
    with monkeypatch.context() as patch:
        patch.setattr(FinanceCipher, '__init__', lambda *a, **k: pytest.fail('key access/creation'))
        patch.setattr(FinanceStore, '__init__', lambda *a, **k: pytest.fail('store initialized'))
        async with TestClient(TestServer(app.app), headers=client_headers('webui')) as client:
            response = await client.get('/v1/finance/review')
            assert response.status == 200
            assert (await response.json())['state'] == 'not_initialized'
    assert not (root/'finance').exists()
    async with TestClient(TestServer(app.app), headers=client_headers('jaegerd')) as client:
        assert (await client.get('/v1/finance/review')).status == 403
    async with TestClient(TestServer(app.app), headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/finance/review')).status == 403
        assert (await client.post('/v1/finance/actions/act_000000000001/review', json={})).status == 403


@pytest.mark.asyncio
async def test_http_scope_review_receipt_no_effect_and_redaction(setup, monkeypatch):
    root, app = setup; store = existing(root)
    action(store)
    action(store, 'act_000000000002', kind='make_payment', payload={'amount':'4.12','currency':'USD','merchant':'Owned shop','card_number':'4111111111111111','token':'fixture-secret-never-returned'})
    before = store.db_path.stat().st_mode
    with monkeypatch.context() as patch:
        patch.setattr(FinanceCipher, '__init__', lambda *a, **k: pytest.fail('key accessed'))
        async with TestClient(TestServer(app.app), headers=client_headers('webui')) as client:
            snapshot = await (await client.get('/v1/finance/review')).json()
            serialized = json.dumps(snapshot)
            assert '4111111111111111' not in serialized and 'fixture-secret-never-returned' not in serialized
            assert 'Private rationale' not in serialized
            local = next(row for row in snapshot['actions'] if row['id']=='act_000000000001')
            blocked = next(row for row in snapshot['actions'] if row['id']=='act_000000000002')
            assert local['can_record_review'] and not blocked['can_record_review']
            assert blocked['declared_scope'] == {'amount':'4.12','currency':'USD','merchant':'Owned shop'}
            bad = await client.post('/v1/finance/actions/'+blocked['id']+'/review', json={'operation_id':'blocked-approve','expected_revision':blocked['revision'],'decision':'record_review'})
            assert bad.status == 403 and (await bad.json())['execution_performed'] is False
            body = {'operation_id':'owned-review','expected_revision':local['revision'],'decision':'record_review'}
            response = await client.post('/v1/finance/actions/'+local['id']+'/review', json=body)
            result = await response.json()
            assert response.status == 200 and result['status']=='approved' and result['review_only'] and not result['execution_performed']
            assert await (await client.post('/v1/finance/actions/'+local['id']+'/review', json=body)).json() == result
            assert (await (await client.get('/v1/finance/operations/owned-review')).json())['receipt'] == result
            assert (await client.post('/v1/finance/actions/'+local['id']+'/review', json={**body,'amount':9999})).status == 400
    assert store.db_path.stat().st_mode == before
    assert store.get_budgets('2026-10') == [] and store.get_accounts() == []
    assert AuditLog(store).verify_integrity()['ok']
    assert len([r for r in store.get_audit_log() if r['action']=='review_decision']) == 2
    assert not list((root/'finance').glob('*.key'))


def test_two_connection_review_cas_and_unknown_preservation(setup):
    root, _ = setup; store = existing(root); action(store)
    row = review.snapshot(store)['actions'][0]
    def decide(decision):
        return review.decide(FinanceStore.open_existing(readonly=False), row['id'], decision,
                             expected_revision=row['revision'], operation_id='race-'+decision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ('record_review', 'deny')))
    assert sum(r['ok'] for r in results) == 1
    assert next(r for r in results if not r['ok'])['status'] == 'conflict'
    action(store, 'act_000000000003', status='execution_unknown')
    uncertain = next(r for r in review.snapshot(store)['actions'] if r['id']=='act_000000000003')
    assert not uncertain['can_record_review'] and not uncertain['can_deny']
    for decision in ('record_review','deny'):
        result = review.decide(store, uncertain['id'], decision, expected_revision=uncertain['revision'], operation_id='unknown-'+decision)
        assert not result['ok'] and result['status']=='execution_unknown' and not result['execution_performed']
    assert store.get_pending_actions(status='execution_unknown')[0].id == uncertain['id']
    assert AuditLog(store).verify_integrity()['ok']


def test_expiration_at_final_commit_rolls_back_approved_review(setup, monkeypatch):
    root, _ = setup; store = existing(root); action(store)
    row = review.snapshot(store)['actions'][0]
    expired = False; original = store.append_audit
    def insert_then_expire(*args, **kwargs):
        nonlocal expired
        result = original(*args, **kwargs)
        expired = True
        return result
    monkeypatch.setattr(store, 'append_audit', insert_then_expire)
    monkeypatch.setattr(review, '_expired', lambda row: expired)
    result = review.decide(store, row['id'], 'record_review', expected_revision=row['revision'], operation_id='expires-at-commit')
    assert not result['ok'] and result['status']=='expired'
    assert store.get_pending_actions(status='expired')[0].id == row['id']
    assert len(store.get_audit_log()) == 1
    assert store.get_audit_log()[0]['details']['receipt']['status']=='expired'
    assert not result['execution_performed']


@pytest.mark.asyncio
async def test_lost_postcommit_response_recovers_original_receipt_without_resubmit(setup, monkeypatch):
    root, app = setup; store = existing(root); action(store)
    row = review.snapshot(store)['actions'][0]
    async with TestClient(TestServer(app.app), headers=client_headers('webui')) as client:
        with monkeypatch.context() as patch:
            patch.setattr(app.event_bus, 'publish', lambda *a: (_ for _ in ()).throw(RuntimeError('owned response loss')))
            response = await client.post('/v1/finance/actions/'+row['id']+'/review', json={'operation_id':'lost-review','expected_revision':row['revision'],'decision':'deny'})
            assert response.status == 500
        result = (await (await client.get('/v1/finance/operations/lost-review')).json())['receipt']
        assert result['ok'] and result['status']=='rejected' and not result['execution_performed']
    assert len(store.get_audit_log()) == 1


def test_proxy_only_supported_financial_review_paths(monkeypatch):
    from urllib.parse import urlparse

    from jaeger_ai.features.webui.api import jaeger_sessions as proxy
    calls = []
    monkeypatch.setattr(proxy, '_proxy', lambda *args: calls.append(args) or True)
    monkeypatch.setattr(proxy, '_body_bytes', lambda handler: b'owned-body')
    for path, method in [('/v1/finance/review', 'GET'), ('/v1/finance/operations/owned', 'GET'), ('/v1/finance/actions/act_owned/review', 'POST')]:
        assert proxy.route(object(), urlparse(path), method)
        assert calls[-1][1:3] == (method, path)
    for path, method in [('/v1/finance/review', 'POST'), ('/v1/finance/actions/a/payment', 'POST'), ('/v1/finance/operations/a/extra', 'GET')]:
        assert not proxy.route(object(), urlparse(path), method)


def test_status_import_does_not_activate_tools_or_provider(tmp_path):
    import os
    import subprocess
    import sys
    code = "import sys; from jaeger_ai.features.finance import routes; assert 'jaeger_ai.features.finance.tools' not in sys.modules; assert 'jaeger_ai.features.finance.providers.monarch' not in sys.modules"
    result = subprocess.run([sys.executable, '-B', '-c', code], env={**os.environ, 'JAEGER_STATE_DIR':str(tmp_path), 'JAEGER_HOME':str(tmp_path)}, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_projection_refuses_unknown_status_and_nonobject_scope(setup):
    root, _ = setup; store = existing(root)
    action(store, status='unsafe-token-fixture')
    projected = review.snapshot(store)['actions'][0]
    assert projected['status'] == 'unsupported_status'
    assert 'unsafe-token-fixture' not in json.dumps(projected)
    assert not projected['can_record_review'] and not projected['can_deny']
