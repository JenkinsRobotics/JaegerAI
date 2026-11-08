"""Real resident-return producer and independent owner verification, no network."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jaeger_agent.memory import sqlite_store
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.owner_receipts import OwnerReceiptConflict
from jaeger_ai.core.tasks import background_receipts
from dev.tests.jaeger_ai.core.test_owner_request_journal import Runtime, Crash


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    monkeypatch.delenv('JAEGER_LEGACY_PATHS', raising=False)
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path/'memory'))
    runtime = Runtime(tmp_path)
    monkeypatch.setattr(EntityRuntime, 'get_singleton', classmethod(lambda cls: runtime))
    store = GatewaySessionStore(tmp_path/'gateway.sqlite3')
    app = JaegerGatewayApp(store=store)
    app._owner_receipt_lease = store.claim_process()
    defaults = {'workspace': str(tmp_path), 'model': 'scripted', 'provider': 'openai', 'route_fingerprint': 'route-v1'}
    monkeypatch.setattr(app, '_foreground_execution_defaults', lambda: deepcopy(defaults))
    monkeypatch.setattr(app, '_current_tier', lambda: 'jaeger')
    monkeypatch.setattr(app, '_schedule_summary', lambda sid: None)
    assert app._registry().get_agent('native:jaeger').role.value == 'lead'
    store.ensure_session('parent', metadata={'agent_id': 'native:jaeger', 'agent_pinned': True})
    artifact = tmp_path/'report.txt'
    tid = app.task_owner.submit('Write the report', artifacts=[str(artifact)], canonical_background=True,
        context={'source': 'client', 'session_id': 'parent', 'execution': {'caller': 'webui', 'workspace': str(tmp_path)}})['task_id']
    def produce(native):
        from jaeger_ai.core.runtime.work_ledger import work_ledger, complete_task
        artifact.write_text('OWNER-VERIFIED-REPORT')
        assert work_ledger(action='create', task_name='Report', total_items=1,
                           verify={'kind': 'paths_exist', 'paths': [str(artifact)]})['ok']
        assert work_ledger(action='update', completed_ids=['report'], remaining_count=0)['ok']
        assert complete_task(summary='Finished answer.', evidence='Read back the report')['ok']
    runtime.before_answer = produce
    yield SimpleNamespace(app=app, store=store, runtime=runtime, tid=tid, rid=tid+':0', artifact=artifact)
    sqlite_store.close()


def journal(env):
    with env.store._get_conn() as conn:
        row = conn.execute('SELECT * FROM background_request_journal WHERE request_id=?', (env.rid,)).fetchone()
        return dict(row) if row else None


def pending_effect(native):
    def lost_effect():
        raise RuntimeError('Synthetic effect outcome was lost')
    with pytest.raises(RuntimeError, match='Synthetic effect'):
        SqliteEffectLedger().once('unresolved-effect', 'write', lost_effect, run_id=native)
    assert SqliteEffectLedger().get('unresolved-effect').status == 'pending'


async def crash(env, monkeypatch, phase='after_seal'):
    if phase == 'after_seal':
        def stop(*args, **kwargs):
            raise Crash()
        monkeypatch.setattr(env.app, '_persist_terminal', stop)
    else:
        monkeypatch.setattr(env.app, '_commit_background_outcome', lambda *args: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        await env.app.task_owner._execute(env.tid)
    assert env.runtime.calls == 1
    assert env.artifact.read_text() == 'OWNER-VERIFIED-REPORT'


def restart(env):
    store = GatewaySessionStore(env.store.path)
    app = JaegerGatewayApp(store=store)
    app._owner_receipt_lease = store.claim_process()
    store.recover_interrupted_sessions()
    return app


@pytest.mark.asyncio
async def test_returned_final_producer_seals_exact_output_and_owner_evidence(env):
    await env.app.task_owner._execute(env.tid)
    saved = journal(env)
    proof = env.store.owner_request_receipt(env.rid)
    assert saved['terminal_json'] and proof['source'] == background_receipts.SOURCE
    assert proof['result'] == env.store.get_request(env.rid)['result']
    assert proof['assistant_text'] == 'Finished answer.'
    assert proof['verification'] == env.app.task_owner.store.get_task(env.tid).payload['verification']
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'completed_verified'
    assert not env.store.has_owner_request_journal(env.rid)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['before_seal', 'after_seal'])
async def test_crash_seal_boundary_is_recoverable_once_without_execution(env, monkeypatch, phase):
    await crash(env, monkeypatch, phase)
    saved = journal(env)
    assert bool(saved['terminal_json']) == (phase == 'after_seal')
    native = env.store.get_request(env.rid)['native_run_id']
    assert SqliteRunStore().get(native).state == 'active'  # Never fake completion to obtain proof.
    for _ in range(2):
        app = restart(env)
        recovered = app._recover_sealed_owner_results()
        expected = 'completed' if phase == 'after_seal' else 'execution_unknown'
        assert app.store.get_request(env.rid)['status'] == expected
        assert recovered in {0, 1}
        assert app._recover_sealed_owner_results() == 0
        assert env.runtime.calls == 1
    events = [e for e in app.event_bus.get_replay_events('task:'+env.tid) if e.event == 'turn.reconciled']
    assert len(events) == int(phase == 'after_seal')
    assert journal(env)['terminal_json'] == saved['terminal_json']


def mutate(env, change):
    owner = env.app.task_owner
    if change in {'goal', 'tools', 'authority', 'revoke', 'cancel', 'attempt', 'agent', 'research'}:
        def edit(task):
            if change == 'goal': task.goal = 'Foreign objective'
            if change == 'tools': task.payload['execution']['allowed_tools'] = ['foreign']
            if change == 'authority': task.payload['background_authority']['goal'] = 'Forged grant'
            if change == 'revoke': task.provenance['authorized'] = False
            if change == 'cancel': task.cancellation = 'Stopped'
            if change == 'attempt': task.payload['attempt'] = 1
            if change == 'agent': task.agent_id = 'foreign'
            if change == 'research': task.payload['research_contract'] = {'changed': True}
        owner.store.update_task(env.tid, edit)
    elif change == 'session':
        env.store.ensure_session('task:'+env.tid, metadata={'agent_id': 'foreign'})
    elif change == 'artifact':
        env.artifact.write_text('SUBSTITUTED-REPORT')
    elif change in {'lease-pid', 'lease-generation', 'native', 'identity', 'output', 'evidence'}:
        with env.store._immediate() as conn:
            if change == 'lease-pid': conn.execute('UPDATE process_lease SET owner_pid=-1 WHERE id=1')
            if change == 'lease-generation': conn.execute('UPDATE process_lease SET started_at=started_at+1 WHERE id=1')
            if change == 'native': conn.execute("UPDATE client_requests SET native_run_id='foreign' WHERE request_id=?", (env.rid,))
            if change == 'identity': conn.execute("UPDATE client_requests SET digest='foreign' WHERE request_id=?", (env.rid,))
            if change in {'output', 'evidence'}:
                proof = json.loads(conn.execute('SELECT terminal_json FROM background_request_journal WHERE request_id=?', (env.rid,)).fetchone()[0])
                if change == 'output': proof['result']['output'] = proof['assistant_text'] = 'SUBSTITUTED-ANSWER'
                else: proof['verification'][0]['sha256'] = 'foreign'
                conn.execute('UPDATE background_request_journal SET terminal_json=? WHERE request_id=?', (json.dumps(proof), env.rid))


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['goal', 'tools', 'authority', 'revoke', 'cancel', 'attempt', 'agent', 'research',
                                    'session', 'artifact', 'native', 'identity', 'output', 'evidence'])
async def test_seal_to_projection_drift_never_overwrites_or_reexecutes(env, monkeypatch, change):
    await crash(env, monkeypatch)
    mutate(env, change)
    task_before = env.app.task_owner.store.get_task(env.tid).to_dict()
    for _ in range(2):
        app = restart(env)
        assert app._recover_sealed_owner_results() == 0
        assert app.store.get_request(env.rid)['status'] == 'execution_unknown'
        assert app.task_owner.store.get_task(env.tid).to_dict() == task_before
    assert env.runtime.calls == 1
    assert not [e for e in app.event_bus.get_replay_events('task:'+env.tid) if e.event == 'turn.reconciled']


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['goal', 'tools', 'authority', 'revoke', 'cancel', 'attempt', 'agent', 'research',
                                    'session', 'lease-pid', 'lease-generation', 'native', 'identity'])
async def test_seal_rechecks_live_identity_and_grant(env, monkeypatch, change):
    original = env.app._commit_background_outcome
    def changed(*args):
        mutate(env, change)
        return original(*args)
    monkeypatch.setattr(env.app, '_commit_background_outcome', changed)
    await env.app.task_owner._execute(env.tid)
    assert journal(env)['terminal_json'] is None
    assert env.runtime.calls == 1
    assert env.app.task_owner.store.get_task(env.tid).state.value != 'completed_verified'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing', 'foreign-owner', 'failed', 'pending', 'children', 'foreign-token'])
async def test_seal_requires_settled_owned_native_operations(env, monkeypatch, change):
    original = env.app._commit_background_outcome
    def changed(rid, token, result, text):
        if change == 'children':
            monkeypatch.setattr(env.app.task_owner, '_background_children_unsettled', lambda row: True)
        elif change == 'pending':
            native = env.store.get_request(rid)['native_run_id']
            pending_effect(native)
        elif change == 'foreign-token':
            token = 'foreign'
        else:
            previous = SqliteRunStore.get
            def get(store, native):
                run = previous(store, native)
                if change == 'missing': return None
                if change == 'foreign-owner': run.owner_pid = -1
                if change == 'failed': run.state = 'failed'
                return run
            monkeypatch.setattr(SqliteRunStore, 'get', get)
        return original(rid, token, result, text)
    monkeypatch.setattr(env.app, '_commit_background_outcome', changed)
    await env.app.task_owner._execute(env.tid)
    assert not journal(env)['terminal_json']
    assert env.store.get_request(env.rid)['status'] == 'execution_unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,halt', [('', None), ('Partial report', 'yielded'), ('Need owner', 'needs_owner'), ('Blocked', 'blocked')])
async def test_unsupported_returned_slices_do_not_gain_terminal_proof(env, answer, halt):
    env.runtime.before_answer = lambda native: env.artifact.write_text('OWNER-VERIFIED-REPORT')
    env.runtime.answers = [(answer, halt)] * 9
    await env.app.task_owner._execute(env.tid)
    assert not journal(env)['terminal_json']


@pytest.mark.asyncio
async def test_native_binding_cannot_mutate_sealed_proof(env, monkeypatch):
    await crash(env, monkeypatch)
    saved = journal(env)
    with pytest.raises(OwnerReceiptConflict):
        env.store.bind_native(env.rid, native_run_id='late', native_session='owner:task:'+env.tid,
                              native_binding_guard=env.app.task_owner.background_binding_guard)
    assert journal(env) == saved


@pytest.mark.asyncio
@pytest.mark.parametrize('child_state', [None, 'approved', 'completed', 'execution_unknown'])
async def test_rotated_native_child_exclusion_covers_every_accepted_run(env, child_state):
    produce = env.runtime.before_answer
    first = []
    def rotated(native):
        if not first:
            first.append(native)
            SqliteRunStore().transition(native, 'completed')
            if child_state:
                env.store.save_handoff({'id': 'earlier-child', 'from_agent_id': 'native:jaeger',
                    'to_agent_id': 'foreign-child', 'parent_run_id': native,
                    'task': 'Earlier native child', 'status': child_state})
        else:
            produce(native)
    env.runtime.before_answer = rotated
    env.runtime.answers = [('First run returned, continue', None), ('Finished answer.', None)]
    await env.app.task_owner._execute(env.tid)
    contract = env.app.task_owner.store.get_task(env.tid).payload['background_admissions'][env.rid]
    assert len(contract['native_run_ids']) == 2
    assert contract['native_run_ids'][0] == first[0]
    assert bool(journal(env)['terminal_json']) == (child_state is None)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['checkpoint', 'effect', 'missing-native', 'foreign-alias', 'child', 'request-cancel'])
async def test_native_evidence_and_request_stop_survive_seal_to_projection_race(env, monkeypatch, change):
    await crash(env, monkeypatch)
    native = env.store.get_request(env.rid)['native_run_id']
    if change == 'checkpoint':
        SqliteRunStore().checkpoint(native, {'foreign': True})
    elif change == 'effect':
        pending_effect(native)
    elif change == 'missing-native':
        monkeypatch.setattr(SqliteRunStore, 'get', lambda *args: None)
    elif change == 'foreign-alias':
        env.store.admit_request('foreign', 'foreign', request_id='foreign')
        with env.store._immediate() as conn:
            conn.execute('UPDATE client_requests SET native_run_id=? WHERE request_id=?', (native, 'foreign'))
    elif change == 'child':
        env.store.save_handoff({'id': 'late-child', 'from_agent_id': 'native:jaeger', 'to_agent_id': 'foreign-child',
            'parent_run_id': native, 'task': 'Late child', 'status': 'completed'})
    else:
        env.store.mark_request_status(env.rid, 'cancelling')
        assert journal(env)['revoked'] == 1
    for _ in range(2):
        app = restart(env)
        assert app._recover_sealed_owner_results() == 0
        assert app.store.get_request(env.rid)['status'] == 'execution_unknown'
        assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_background_journal_never_borrows_foreign_bridge_receipt(env, monkeypatch):
    await crash(env, monkeypatch)
    with env.store._immediate() as conn:
        conn.execute("UPDATE client_requests SET native_session='forged-bridge' WHERE request_id=?", (env.rid,))
    app = restart(env)
    monkeypatch.setattr(app, '_native_receipt', lambda *args: (_ for _ in ()).throw(AssertionError('Foreign fallback')))
    from dev.tests.jaeger_ai.core.test_owner_request_journal import Request
    response = await app.handle_reconcile(Request(request_id=env.rid, session='task:'+env.tid))
    assert response.status == 409
    assert app.store.get_request(env.rid)['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_background_recovery_is_fenced_by_current_gateway_generation(env, monkeypatch):
    await crash(env, monkeypatch)
    app = restart(env)
    with app.store._immediate() as conn:
        conn.execute('UPDATE process_lease SET started_at=started_at+1 WHERE id=1')
    with pytest.raises(OwnerReceiptConflict):
        app._recover_sealed_owner_results()
    assert app.store.get_request(env.rid)['status'] == 'execution_unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['lease-pid', 'lease-generation', 'missing-lease'])
async def test_sealed_projection_cannot_be_written_by_stale_or_unfenced_caller(env, monkeypatch, change):
    await crash(env, monkeypatch)
    proof = env.store.owner_request_receipt(env.rid)
    lease = env.app._owner_receipt_lease
    if change != 'missing-lease':
        mutate(env, change)
    with pytest.raises(OwnerReceiptConflict):
        env.store.complete_request(env.rid, **{key: proof[key] for key in
            ('status', 'result', 'assistant_text', 'session_status', 'follow_ups')},
            owner_recovery_lease=lease if change != 'missing-lease' else None)
    assert env.store.get_request(env.rid)['status'] == 'running'
    assert not [e for e in env.app.event_bus.get_replay_events('task:'+env.tid) if e.event == 'turn.finish']


@pytest.mark.asyncio
async def test_background_producer_never_acquires_foreground_journal_identity(env):
    from jaeger_ai.core.gateway.owner_receipts import begin
    def before_bind(native, kwargs):
        assert journal(env) is not None
        assert env.store.get_request(env.rid)['native_run_id'] is None
        with pytest.raises(OwnerReceiptConflict, match='foreground producer'):
            begin(env.store, env.rid, 'task:'+env.tid, env.app._owner_receipt_lease)
    env.runtime.before_bind = before_bind
    await env.app.task_owner._execute(env.tid)
    assert journal(env)['terminal_json']
    assert not env.store.has_owner_request_journal(env.rid)
