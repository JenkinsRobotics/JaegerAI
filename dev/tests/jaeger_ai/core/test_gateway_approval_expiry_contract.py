"""Expired proposal decisions cannot admit work through the legacy HTTP route.

Owned Gateway process, production task owner and SQLite; only the provider is
scripted. The fixture changes the saved deadline, not the resolution path.
"""
import json
import sqlite3
import time
from urllib.error import HTTPError

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


@pytest.mark.parametrize('on_expire', ['deny', 'escalate'])
def test_expired_proposal_cannot_admit_work_before_inbox_sweep(tmp_path, on_expire):
    gateway = OwnedGateway(tmp_path)
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id': 'expiry-parent', 'profile': 'jaeger'})
        _, submitted = gateway.request('/v1/tasks', {
            'session_id': 'expiry-parent', 'goal': 'Say CONTRACT-ANSWER', 'proposal': True,
        })
        task_id = submitted['task_id']
        # Observe the live approval before expiring it, then never call the
        # inbox GET (which happens to sweep expiry) before attempting approval.
        approvals = gateway.request('/v1/approvals')[1]['approvals']
        approval = next(a for a in approvals if a['metadata'].get('task_id') == task_id)
        with sqlite3.connect(tmp_path / 'gateway_sessions.sqlite3') as conn:
            metadata = {**approval['metadata'], 'expires_at': time.time() - 60,
                        'on_expire': on_expire}
            conn.execute('UPDATE approvals SET metadata_json=? WHERE approval_id=?',
                         (json.dumps(metadata), approval['approval_id']))
        with pytest.raises(HTTPError) as refused:
            gateway.request('/v1/approvals/' + approval['approval_id'],
                            {'approved': True, 'decision': 'once'})
        assert refused.value.code == 409
        _, task = gateway.request('/v1/tasks/' + task_id)
        assert task['state'] == 'paused'
        assert not task['provenance']['authorized']
        assert not task['run_history']
        # Restart without polling the inbox must not convert an expired answer
        # into durable authority or produce a worker/provider invocation.
        gateway.stop()
        gateway.start()
        with pytest.raises(HTTPError) as replay:
            gateway.request('/v1/approvals/' + approval['approval_id'],
                            {'approved': True, 'decision': 'once'})
        assert replay.value.code == 409
        _, task = gateway.request('/v1/tasks/' + task_id)
        assert task['state'] == 'paused'
        assert not task['run_history']
        assert not (tmp_path / 'provider-calls.jsonl').exists()
    finally:
        gateway.stop()


@pytest.mark.parametrize('expired,on_expire,approved,expected', [
    (False, 'deny', True, True),
    (False, 'deny', False, True),
    (True, 'keep', True, True),
    (True, 'deny', False, True),
    (True, 'escalate', False, True),
    (True, 'deny', True, False),
    (True, 'escalate', True, False),
])
def test_sqlite_resolution_preserves_valid_and_negative_decisions(
        tmp_path, expired, on_expire, approved, expected):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / 'resolution.sqlite3')
    row = store.create_approval(
        kind='background_task', prompt='Saved objective', options=['once', 'deny'],
        session_id='parent', metadata={
            'expires_at': time.time() + (-60 if expired else 3600),
            'on_expire': on_expire,
        })
    decision = 'once' if approved else 'deny'
    result = store.resolve_approval(row['approval_id'], approved=approved, decision=decision)
    assert (result is not None) == expected
    if expected:
        assert result['decision'] == decision
        assert store.resolve_approval(row['approval_id'], approved=not approved) is None
        assert store.get_approval(row['approval_id'])['decision'] == decision
    else:
        assert store.get_approval(row['approval_id'])['status'] == 'pending'
        assert store.resolve_approval(row['approval_id'], approved=False,
                                      decision='expired')['decision'] == 'expired'


def test_unoffered_persistent_scope_cannot_approve_real_tool(tmp_path):
    gateway = OwnedGateway(tmp_path)
    try:
        gateway.start()
        gateway.request('/v1/sessions', {'session_id': 'scope-parent', 'profile': 'jaeger'})
        gateway.request('/v1/sessions/scope-parent/turns', {
            'text': 'CONTRACT-WRITE: write the test file', 'request_id': 'scope-request',
        })
        deadline = time.monotonic() + 10
        approvals = []
        while time.monotonic() < deadline:
            approvals = gateway.request('/v1/approvals')[1]['approvals']
            if approvals:
                break
            time.sleep(0.05)
        assert len(approvals) == 1
        approval = approvals[0]
        assert 'always' not in approval['options']
        with pytest.raises(HTTPError) as refused:
            gateway.request('/v1/approvals/' + approval['approval_id'],
                            {'approved': True, 'decision': 'always'})
        assert refused.value.code == 409
        _, pending = gateway.request('/v1/approvals/' + approval['approval_id'])
        assert pending['status'] == 'pending'
        permissions = tmp_path / 'instances/contract/permissions.json'
        assert not permissions.exists() or not json.loads(permissions.read_text()).get('granted_skills')
        # A rejected scope does not consume a legitimate subsequent answer.
        gateway.request('/v1/approvals/' + approval['approval_id'],
                        {'approved': False, 'decision': 'deny'})
        gateway.wait_for_terminal('scope-parent', 'scope-request')
        assert not (tmp_path / 'instances/contract/workspace/contract-output.txt').exists()
    finally:
        gateway.stop()


@pytest.mark.parametrize('deadline', ['yesterday', float('nan'), float('inf'), True])
def test_invalid_saved_deadline_fails_closed(tmp_path, deadline):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / 'deadline.sqlite3')
    row = store.create_approval(kind='tool_confirm', prompt='Write', options=['once', 'deny'],
                                metadata={'expires_at': deadline})
    assert store.resolve_approval(row['approval_id'], approved=True, decision='once') is None
    assert store.resolve_approval(row['approval_id'], approved=False, decision='expired')


@pytest.mark.parametrize('options,choice,accepted', [
    (['once', 'deny'], 'session', False),
    (['once', 'session', 'deny'], 'always', False),
    (['once', 'session', 'deny'], 'session', True),
    (['once', 'always', 'deny'], 'always', True),
    (['once', 'deny'], 'allow', True),
    (['once', 'deny'], 'yes', True),
    (['allow', 'deny'], 'allow', True),
    (['yes', 'deny'], 'once', True),
    (['deny'], 'yes', False),
])
def test_resolution_cannot_expand_offered_scope(tmp_path, options, choice, accepted):
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / 'scope.sqlite3')
    row = store.create_approval(kind='tool_confirm', prompt='Write', options=options)
    result = store.resolve_approval(row['approval_id'], approved=True, decision=choice)
    assert (result is not None) == accepted


def test_expiry_is_checked_after_waiting_for_sqlite_writer(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / 'contended.sqlite3')
    deadline = time.time() + 0.5
    row = store.create_approval(kind='tool_confirm', prompt='Write', options=['once', 'deny'],
                                metadata={'expires_at': deadline})
    entered = threading.Event()

    def answer():
        entered.set()
        return store.resolve_approval(row['approval_id'], approved=True, decision='once')

    with sqlite3.connect(store.path) as writer, ThreadPoolExecutor(max_workers=1) as pool:
        writer.execute('BEGIN IMMEDIATE')
        future = pool.submit(answer)
        try:
            assert entered.wait(2)
            # Real SQLite contention, not a mocked clock or transaction. The
            # request begins in time but cannot acquire authority until late.
            time.sleep(max(0, deadline - time.time()) + 0.05)
            assert not future.done()
        finally:
            writer.commit()
        assert future.result(timeout=5) is None
    assert store.get_approval(row['approval_id'])['status'] == 'pending'


def test_concurrent_cancel_and_approve_have_one_durable_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    store = GatewaySessionStore(tmp_path / 'concurrent.sqlite3')
    row = store.create_approval(kind='tool_confirm', prompt='Write', options=['once', 'deny'])
    start = threading.Barrier(2)

    def answer(approved):
        start.wait(timeout=5)
        return store.resolve_approval(row['approval_id'], approved=approved,
                                      decision='once' if approved else 'cancelled')

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(answer, [True, False]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    # Cancellation does not undo an already committed approval. Whichever
    # transaction wins is immutable; the loser cannot manufacture a receipt.
    assert store.get_approval(row['approval_id'])['decision'] == winners[0]['decision']
    assert store.resolve_approval(row['approval_id'], approved=True, decision='once') is None
