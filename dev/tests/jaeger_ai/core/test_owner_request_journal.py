"""Full Gateway producer -> request journal -> restart projection, no network.

Script only the model/runtime port. Use the real continued owner runner,
TurnExecutive, checkpoints/effects, admission/lease, and terminal producer.
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from jaeger_agent.cognition.executive import TurnExecutive
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
from jaeger_agent.memory import sqlite_store

from jaeger_ai.core.entity.ownership import EntityRuntimeMode
from jaeger_ai.core.entity.runtime import EntityRuntime
from jaeger_ai.core.gateway import owner_receipts
from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX, JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class Crash(BaseException):
    """Controlled process-loss boundary; not a normal worker exception."""


class Request(dict):
    can_read_body = True

    def __init__(self, request_id='r', session='s', **body):
        super().__init__()
        self.match_info = {'id': session}
        self.body = {'request_id': request_id, **body}

    async def json(self):
        return self.body


class Loop:
    run_id = None
    last_iteration_count = 1
    primary_adapter = SimpleNamespace(name='scripted')

    def __init__(self, runtime):
        self.runtime = runtime
        self.last_halt_reason = None
        self.messages = []

    def bind_run(self, run_id):
        self.run_id = run_id

    def run_turn(self, prompt):
        runtime = self.runtime
        runtime.calls += 1
        if runtime.before_answer:
            runtime.before_answer(self.run_id)
        text, self.last_halt_reason = runtime.answers.pop(0)
        self.messages.append({'role': 'assistant', 'content': text})
        return text


class Runtime:
    mode = EntityRuntimeMode.OWNER
    is_resident = True

    def __init__(self, root):
        self.layout = SimpleNamespace(workspace_dir=root)
        self.answers = [('Finished answer.', None)]
        self.calls = 0
        self.runs = []
        self.before_answer = None
        self.before_bind = None
        self.returned = threading.Event()
        self.observed_authority = []

    def prepare_turn(self, text, **kwargs):
        return SimpleNamespace(prompt=text, context_references=(), event=SimpleNamespace())

    def finish_turn(self, *args):
        pass

    def run_subordinate_react(self, prompt, **kwargs):
        from jaeger_agent.tool_executor import (
            active_caller_identity,
            active_tool_allowlist,
        )
        self.observed_authority.append((active_caller_identity(), active_tool_allowlist()))
        state = kwargs['continuation_state']
        loop = state.setdefault('scripted_loop', Loop(self))
        if kwargs.get('native_run_id'):
            loop.bind_run(kwargs['native_run_id'])
        from jaeger_agent.task_port import current_task_context
        durable = bool(((current_task_context() or {}).get('execution', {}).get('options') or {}).get('task_id'))
        executive = TurnExecutive(loop, SqliteRunStore(), SqliteCommitmentStore(), provider='scripted', durable_task=durable)
        run = executive.ensure_run()
        self.runs.append(run.id)
        if self.before_bind:
            self.before_bind(run.id, kwargs)
        kwargs['on_run'](run.id)
        try:
            return {'text': executive.run_turn(prompt), 'halt_reason': loop.last_halt_reason}
        finally:
            self.returned.set()


@pytest.fixture
def env(tmp_path, monkeypatch, request):
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('JAEGER_AUTO_CONTINUE', '1')
    monkeypatch.delenv('JAEGER_LEGACY_PATHS', raising=False)
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path / 'memory'))
    runtime = Runtime(tmp_path)
    monkeypatch.setattr(EntityRuntime, 'get_singleton', classmethod(lambda cls: runtime))
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    app = JaegerGatewayApp(store=store)
    app._owner_receipt_lease = store.claim_process()
    monkeypatch.setattr(app, '_resolve_session_agent', lambda sid: None)
    monkeypatch.setattr(app, '_schedule_summary', lambda sid: None)
    # No task card for this conversational objective. The actual producer,
    # callback, continuation, classification and persistence remain intact.
    choices = dict(getattr(request, 'param', {}))
    prompt = choices.pop('_prompt', 'hello')
    if choices.pop('_workspace', False):
        choices['workspace'] = str(tmp_path)
    row = store.admit_request('s', prompt, request_id='r', requested={
        'model': 'scripted', 'provider': 'scripted', 'allowed_tools': [], 'caller': 'agent:test',
        **choices,
    })
    app._cancellations.register('r')
    yield SimpleNamespace(app=app, store=store, runtime=runtime, row=row)
    sqlite_store.close()


async def execute(env, **kwargs):
    await env.app._execute_turn(env.row['session_id'], env.row['turn_id'], env.row['input_text'], request_id=env.row['request_id'],
                                     execution=kwargs.get('execution', env.row['execution']))


def journal(env):
    with env.store._get_conn() as conn:
        row = conn.execute('SELECT * FROM owner_request_journal WHERE request_id=?', ('r',)).fetchone()
        return dict(row) if row else None


def restart(env):
    app = JaegerGatewayApp(store=GatewaySessionStore(env.store.path))
    app.store.claim_process()
    app.store.recover_interrupted_sessions()
    return app


@pytest.mark.asyncio
async def test_actual_producer_commits_full_snapshot_and_normal_projection(env):
    await execute(env)
    proof = env.store.owner_request_receipt('r')
    assert proof is not None
    assert proof['source'] == owner_receipts.SOURCE
    assert proof['native_run_ids'] == env.runtime.runs
    assert proof['result']['output'] == 'Finished answer.'
    assert proof['status'] == env.store.get_request('r')['status'] == 'completed'
    assert proof['result'] == env.store.get_request('r')['result']
    bound = json.loads(journal(env)['identity_json'])
    assert json.loads(bound['execution_json']) == env.row['execution']
    assert bound['digest'] == env.row['digest']
    assert bound['turn_id'] == env.row['turn_id']
    assert env.runtime.calls == 1
    assert env.runtime.observed_authority == [('agent:test', frozenset())]


@pytest.mark.asyncio
@pytest.mark.parametrize('window', ['before', 'after'])
async def test_controlled_crash_window_requires_committed_whole_request_proof(env, monkeypatch, window):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_commit_owner_outcome' if window == 'before' else '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    app = restart(env)
    started = []
    monkeypatch.setattr(app, '_start_admitted_turn', lambda row, *args: started.append(row))
    app.store.enqueue_request('s', 'next', request_id='next')
    response = await app.handle_reconcile(Request())
    data = json.loads(response.text)
    assert response.status == (200 if window == 'after' else 409)
    assert data['status'] == ('completed' if window == 'after' else 'execution_unknown')
    assert env.runtime.calls == 1
    if window == 'after':
        assert data['result'] == app.store.owner_request_receipt('r')['result']
        assert [row['request_id'] for row in started] == ['next']
        events = app.event_bus.get_replay_events('s')
        again = json.loads((await app.handle_reconcile(Request())).text)
        assert again['already_terminal']
        assert len(app.event_bus.get_replay_events('s')) == len(events)
        assert len([m for m in app.store.get_session('s')['messages'] if m['role'] == 'assistant']) == 1
    else:
        assert started == []
        assert app.store.owner_request_receipt('r') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('pending', [False, True])
async def test_real_continuation_qualifies_every_accepted_run(env, pending):
    env.runtime.answers = [("I'll check that next.", None), ('Finished answer.', None)]
    def effect(run_id):
        if env.runtime.calls == 1:
            def action():
                if pending:
                    raise RuntimeError('scripted unknown effect')
                return {'done': True}
            try:
                SqliteEffectLedger().once('first-effect', 'scripted', action, run_id=run_id)
            except RuntimeError:
                pass
    env.runtime.before_answer = effect
    await execute(env)
    assert env.runtime.calls == 2 and len(set(env.runtime.runs)) == 2
    assert json.loads(journal(env)['native_runs_json']) == env.runtime.runs
    proof = env.store.owner_request_receipt('r')
    if pending:
        assert proof is None
        assert env.store.get_request('r')['status'] == 'execution_unknown'
        assert EntityRuntime.run_has_indeterminate_effects(env.runtime.runs[-1]) is False
        assert EntityRuntime.run_has_indeterminate_effects(env.runtime.runs[0]) is True
    else:
        assert proof['native_run_ids'] == env.runtime.runs
        assert env.store.get_request('r')['status'] == 'completed'


@pytest.mark.asyncio
async def test_producer_failure_is_not_a_request_receipt(env):
    def fail(run_id):
        raise RuntimeError('worker failed')
    env.runtime.before_answer = fail
    await execute(env)
    assert env.store.owner_request_receipt('r') is None
    assert env.store.get_request('r')['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_async_cancelled_worker_cannot_commit_late_proof(env, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def block(run_id):
        entered.set()
        assert release.wait(5)
    env.runtime.before_answer = block
    started = []
    monkeypatch.setattr(env.app, '_drain_session_queue', lambda session: started.append(session))
    task = asyncio.create_task(execute(env))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert env.store.get_request('r')['status'] == 'execution_unknown'
    finally:
        release.set()
        # Wait for this worker's actual producer return before fixture cleanup.
        assert await asyncio.to_thread(env.runtime.returned.wait, 5)
    assert env.store.owner_request_receipt('r') is None
    assert not started
    assert not [e for e in env.app.event_bus.get_replay_events('s') if e.event == 'turn.cancelled']
    assert json.loads((await restart(env).handle_reconcile(Request())).text)['execution_unknown'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['token', 'lease', 'authority', 'digest', 'session', 'cancel'])
async def test_producer_fences_before_effects(env, change):
    def mutate(run_id, kwargs):
        if change == 'token':
            kwargs['continuation_state']['_owner_receipt_token'] = 'foreign'
        elif change == 'lease':
            env.store.claim_process()  # Same PID, new lease epoch.
        elif change == 'authority':
            with env.store._immediate() as conn:
                conn.execute("UPDATE client_requests SET execution_json='{}' WHERE request_id='r'")
        elif change == 'digest':
            with env.store._immediate() as conn:
                conn.execute("UPDATE client_requests SET digest='foreign' WHERE request_id='r'")
        elif change == 'session':
            env.store.ensure_session('foreign')
            with env.store._immediate() as conn:
                conn.execute("UPDATE client_requests SET session_id='foreign' WHERE request_id='r'")
        else:
            env.app._cancellations.cancel('r')
            env.store.mark_request_status('r', 'cancelling')
    env.runtime.before_bind = mutate
    await execute(env)
    assert env.runtime.calls == 0
    assert journal(env)['terminal_json'] is None
    # Cancellation before any accepted run is known not to have dispatched.
    assert env.store.get_request('r')['status'] == ('cancelled' if change == 'cancel' else 'execution_unknown')


@pytest.mark.asyncio
async def test_late_callbacks_and_conflicting_projection_cannot_change_proof(env):
    await execute(env)
    proof = env.store.owner_request_receipt('r')
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        env.store.bind_native('r', native_run_id='late', native_session=OWNER_RUN_SESSION_PREFIX + 's',
                              owner_receipt_token=journal(env)['producer_token'])
    env.store.mark_request_status('r', 'cancelling')
    assert env.store.get_request('r')['status'] == 'completed'
    assert env.store.owner_request_receipt('r') == proof


@pytest.mark.asyncio
async def test_serialization_failure_does_not_commit_partial_proof(env, monkeypatch):
    original = env.app._commit_owner_outcome
    def invalid(request_id, token, status, result, *args, **kwargs):
        result['invalid'] = float('nan')
        return original(request_id, token, status, result, *args, **kwargs)
    monkeypatch.setattr(env.app, '_commit_owner_outcome', invalid)
    await execute(env)
    assert env.store.owner_request_receipt('r') is None
    assert env.store.get_request('r')['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_noncanonical_execution_gains_no_recovery_authority(env):
    await execute(env, execution={**env.row['execution'], 'caller': 'foreign'})
    assert journal(env) is None
    assert env.store.owner_request_receipt('r') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['lease', 'cancel', 'late_run', 'missing_effect_store'])
async def test_finalization_fences_after_entire_worker_return(env, monkeypatch, change):
    original = env.app._commit_owner_outcome
    def interfere(request_id, token, *args, **kwargs):
        if change == 'lease':
            env.store.claim_process()
        elif change == 'cancel':
            env.app._cancellations.cancel('r')
            env.store.mark_request_status('r', 'cancelling')
        elif change == 'missing_effect_store':
            monkeypatch.setattr(EntityRuntime, 'run_has_indeterminate_effects', staticmethod(lambda _: True))
        else:
            real_finish = owner_receipts.finish
            def late(store, rid, producer, runs, **outcome):
                conn = outcome['conn']
                row = conn.execute('SELECT * FROM client_requests WHERE request_id=?', (rid,)).fetchone()
                owner_receipts.accept(conn, row, 'late', OWNER_RUN_SESSION_PREFIX + 's', producer)
                conn.execute('UPDATE client_requests SET native_run_id=? WHERE request_id=?', ('late', rid))
                return real_finish(store, rid, producer, runs, **outcome)
            monkeypatch.setattr(owner_receipts, 'finish', late)
        return original(request_id, token, *args, **kwargs)
    monkeypatch.setattr(env.app, '_commit_owner_outcome', interfere)
    await execute(env)
    assert env.runtime.calls == 1
    assert env.store.owner_request_receipt('r') is None
    assert env.store.get_request('r')['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_projection_conflict_and_duplicate_proof_are_immutable(env, monkeypatch):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    proof = env.store.owner_request_receipt('r')
    fields = {key: proof[key] for key in ('status', 'result', 'assistant_text', 'session_status', 'follow_ups')}
    assert owner_receipts.finish(env.store, 'r', journal(env)['producer_token'], env.runtime.runs, **fields) == proof
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        owner_receipts.finish(env.store, 'r', journal(env)['producer_token'], env.runtime.runs,
                              **{**fields, 'result': {'output': 'changed'}})
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        env.store.complete_request('r', status='failed', result={'error': 'late exception'})
    env.store.mark_request_status('r', 'cancelling')
    assert env.store.get_request('r')['status'] == 'running'
    app = restart(env)
    assert (await app.handle_reconcile(Request())).status == 200
    assert app.store.owner_request_receipt('r') == proof
    assert app.store.get_request('r')['result'] == proof['result']


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('digest', 'foreign'), ('execution_json', '{}'), ('native_run_id', 'foreign'), ('native_session', 'owner:foreign')])
async def test_reconciliation_refuses_identity_or_authority_drift(env, monkeypatch, field, value):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    with env.store._immediate() as conn:
        conn.execute(f'UPDATE client_requests SET {field}=? WHERE request_id=?', (value, 'r'))
    response = await restart(env).handle_reconcile(Request())
    assert response.status == 409
    assert env.runtime.calls == 1
    assert not [m for m in env.store.get_session('s')['messages'] if m['role'] == 'assistant']


@pytest.mark.asyncio
async def test_historical_receipt_cannot_replace_newer_session_projection(env, monkeypatch):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    app = restart(env)
    app.store.admit_request('s', 'newer', request_id='newer')
    app.store.complete_request('newer', status='failed', result={'error': 'newer failure'})
    assert (await app.handle_reconcile(Request())).status == 200
    assert app.store.get_request('r')['status'] == 'completed'
    assert app.store.get_request('newer')['status'] == 'failed'
    assert app.store.get_session('s')['status'] == 'failed'


@pytest.mark.asyncio
async def test_returned_failed_classification_is_receipted_not_inferred_success(env):
    env.runtime.answers = [('Stopped with a controller failure.', 'controller_failure')]
    await execute(env)
    proof = env.store.owner_request_receipt('r')
    assert proof['status'] == env.store.get_request('r')['status'] == 'failed'
    assert proof['result']['halt_reason'] == 'controller_failure'


@pytest.mark.asyncio
@pytest.mark.parametrize('halt', ['yielded', 'needs_owner', 'blocked'])
async def test_unsupported_owner_outcomes_gain_no_terminal_proof(env, halt):
    env.runtime.answers = [('Stopped here.', halt)]
    await execute(env)
    assert env.store.owner_request_receipt('r') is None


def test_additive_migration_preserves_legacy_without_backfill(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    store = GatewaySessionStore(path)
    store.admit_request('s', 'already done', request_id='old')
    store.complete_request('old', status='completed', result={'output': 'old answer'}, assistant_text='old answer')
    before = store.get_request('old')
    messages = store.get_session('s')['messages']
    with store._immediate() as conn:
        conn.execute('DROP TABLE owner_request_journal')
        conn.execute("UPDATE schema_meta SET value='16' WHERE key='version'")
    upgraded = GatewaySessionStore(path)
    assert upgraded.schema_version() == 17
    assert upgraded.get_request('old') == before
    assert upgraded.get_session('s')['messages'] == messages
    assert upgraded.owner_request_receipt('old') is None
    assert not upgraded.has_owner_request_journal('old')
    assert GatewaySessionStore(path).schema_version() == 17


@pytest.mark.asyncio
@pytest.mark.parametrize('pending', [False, True])
async def test_pending_earlier_effect_controls_queue_events_and_real_task_card(env, monkeypatch, tmp_path, pending):
    env.runtime.identity = SimpleNamespace(entity_id='test', display_name='Test')
    artifact = tmp_path / 'verified.txt'
    artifact.write_text('existing verified artifact')
    opened = []
    def open_card(runtime, prepared, **kwargs):
        card = env.app.task_owner.open_turn(
            session_id='s', request_id='r', text='Inspect the artifact', strategy='react_loop',
            owner='owner', workspace=str(tmp_path), execution=env.row['execution'])
        env.app.task_owner.store.update_task(card.task_id, lambda task: task.payload.update(artifacts=[str(artifact)]))
        opened.append(card.task_id)
        return card.task_id, kwargs['execution']
    monkeypatch.setattr(env.app, '_open_turn_card', open_card)
    env.runtime.answers = [("I'll check that next.", None), ('Finished answer.', None)]
    def effect(run_id):
        if env.runtime.calls == 1:
            def action():
                if pending:
                    raise RuntimeError('unknown earlier effect')
                return True
            try:
                SqliteEffectLedger().once('card-effect', 'scripted', action, run_id=run_id)
            except RuntimeError:
                pass
    env.runtime.before_answer = effect
    env.store.enqueue_request('s', 'queued', request_id='queued')
    started = []
    monkeypatch.setattr(env.app, '_start_admitted_turn', lambda row, *args: started.append(row))
    await execute(env)
    row = env.store.get_request('r')
    task = env.app.task_owner.store.get_task(opened[0])
    events = env.app.event_bus.get_replay_events('s')
    assert env.runtime.calls == 2
    if pending:
        assert env.store.owner_request_receipt('r') is None
        assert row['status'] == 'execution_unknown'
        assert row['result']['status'] == 'execution_unknown'
        assert task.state.value == 'paused'
        assert started == [] and env.store.get_request('queued')['status'] == 'queued'
        assert not any(e.event == 'turn.finish' and e.data.get('request_id') == 'r' for e in events)
        assert not any(e.event == 'task.updated' and e.data['task']['state'] == 'completed_verified' for e in events)
        assert not [m for m in env.store.get_session('s')['messages'] if m['role'] == 'assistant']
    else:
        assert row['status'] == 'completed'
        assert task.state.value == 'completed_verified'
        proof = env.store.owner_request_receipt('r')
        assert proof['result']['receipt']['state'] == 'completed_verified'
        assert proof['result'] == row['result']
        assert [r['request_id'] for r in started] == ['queued']


@pytest.mark.asyncio
async def test_completed_empty_no_tool_result_is_a_real_receipt(env):
    env.runtime.answers = [('', None)]
    await execute(env)
    proof = env.store.owner_request_receipt('r')
    assert proof is not None and proof['status'] == 'completed'
    assert proof['assistant_text'] == '' and proof['result']['output'] == ''
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_lost_or_unknown_producer_cannot_reopen_request_status(env, monkeypatch):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_commit_owner_outcome', crash)
    with pytest.raises(Crash):
        await execute(env)
    env.store.claim_process()
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        env.store.mark_request_status('r', 'running')
    env.store.recover_interrupted_sessions()
    env.store.mark_request_status('r', 'running')
    assert env.store.get_request('r')['status'] == 'execution_unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [
    {'options': {'background': True}}, {'is_subordinate': True},
    {'provider': 'cli'}, {'model': '@framework/default'},
], indirect=True)
async def test_unsupported_modes_are_not_journaled(env):
    await execute(env)
    assert journal(env) is None
    assert env.store.owner_request_receipt('r') is None


@pytest.mark.asyncio
async def test_native_run_cannot_be_reused_by_another_request(env):
    await execute(env)
    env.store.admit_request('other', 'hello again', request_id='other')
    token = owner_receipts.begin(env.store, 'other', 'other', env.app._owner_receipt_lease)
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        env.store.bind_native('other', native_run_id=env.runtime.runs[0],
                              native_session=OWNER_RUN_SESSION_PREFIX + 'other', owner_receipt_token=token)
    assert env.store.get_request('other')['native_run_id'] is None


@pytest.mark.asyncio
async def test_journal_identity_never_falls_back_to_forged_bridge_domain(env, monkeypatch, tmp_path):
    from jaeger_ai.core.runtime.native_turns import NativeTurns
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    native_id = env.runtime.runs[-1]
    with env.store._immediate() as conn:
        conn.execute("UPDATE client_requests SET native_session='bridge-domain' WHERE request_id='r'")
    bridge = NativeTurns(tmp_path / 'run')
    bridge.accept(native_id, 'bridge-domain')
    bridge.finish(native_id, 'bridge-domain', {'text': 'foreign proof'})
    app = restart(env)
    monkeypatch.setattr(app, '_instance_root', lambda: tmp_path)
    response = await app.handle_reconcile(Request())
    assert response.status == 409
    assert json.loads(response.text)['receipt']['source'] == 'resident_owner'
    assert not [m for m in env.store.get_session('s')['messages'] if m['role'] == 'assistant']


def real_card(env, monkeypatch, tmp_path):
    env.runtime.identity = SimpleNamespace(entity_id='test', display_name='Test')
    artifact = tmp_path / 'atomic-artifact.txt'
    artifact.write_text('verified artifact')
    opened = []
    def open_card(runtime, prepared, **kwargs):
        card = env.app.task_owner.open_turn(
            session_id='s', request_id='r', text='Inspect the artifact', strategy='react_loop',
            owner='owner', workspace=str(tmp_path), execution=env.row['execution'])
        env.app.task_owner.store.update_task(card.task_id, lambda task: task.payload.update(artifacts=[str(artifact)]))
        opened.append(card.task_id)
        return card.task_id, {**kwargs['execution'], 'options': {'task_id': card.task_id, 'turn_owned': True}}
    monkeypatch.setattr(env.app, '_open_turn_card', open_card)
    return opened


@pytest.mark.asyncio
@pytest.mark.parametrize('conflict', ['lease', 'authority', 'cancel', 'serialization', 'crash'])
async def test_card_close_and_snapshot_commit_share_one_rollback_boundary(env, monkeypatch, tmp_path, conflict):
    opened = real_card(env, monkeypatch, tmp_path)
    original = owner_receipts.finish
    seen_card_state = []
    live_events = []
    listener = env.store.event_listener
    def observe(record):
        live_events.append(record)
        if listener:
            listener(record)
    env.store.event_listener = observe
    def conflict_after_card(store, rid, token, runs, **kwargs):
        conn = kwargs['conn']
        # This is the actual verifier's state inside the transaction, not a
        # fabricated terminal row. No observer outside it can see this state.
        card = env.app.task_owner.store.get_task_in_transaction(conn, opened[0])
        seen_card_state.append(card.state.value)
        assert env.app.task_owner.store.get_task(opened[0]).state.value != 'completed_verified'
        if conflict == 'lease':
            conn.execute('UPDATE process_lease SET started_at=started_at+1 WHERE id=1')
        elif conflict == 'authority':
            conn.execute("UPDATE client_requests SET digest='changed' WHERE request_id='r'")
        elif conflict == 'cancel':
            env.app._cancellations.cancel('r')
            conn.execute("UPDATE client_requests SET status='cancelling' WHERE request_id='r'")
        elif conflict == 'serialization':
            kwargs['result'] = {**kwargs['result'], 'invalid': float('nan')}
        else:
            raise Crash()
        return original(store, rid, token, runs, **kwargs)
    monkeypatch.setattr(owner_receipts, 'finish', conflict_after_card)
    if conflict == 'crash':
        with pytest.raises(Crash):
            await execute(env)
    else:
        await execute(env)
    assert seen_card_state == ['completed_verified']
    # A later unrelated transaction must not flush events from the rollback,
    # including a BaseException crash boundary.
    with env.store._immediate():
        pass
    assert not any(e['event'] == 'task.updated' and e['data']['task']['state'] == 'completed_verified' for e in live_events)
    assert env.store.owner_request_receipt('r') is None
    events = env.app.event_bus.get_replay_events('s')
    assert not any(e.event == 'task.updated' and e.data['task']['state'] == 'completed_verified' for e in events)
    assert not any(e.event == 'turn.finish' for e in events)
    assert env.app.task_owner.store.get_task(opened[0]).state.value != 'completed_verified'
    if conflict != 'crash':
        assert env.store.get_request('r')['status'] == 'execution_unknown'
        assert env.app.task_owner.store.get_task(opened[0]).state.value == 'paused'
    app = restart(env)
    assert (await app.handle_reconcile(Request())).status == 409
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_atomic_verified_card_and_request_snapshot_survive_projection_crash(env, monkeypatch, tmp_path):
    opened = real_card(env, monkeypatch, tmp_path)
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    proof = env.store.owner_request_receipt('r')
    card = env.app.task_owner.store.get_task(opened[0])
    assert card.state.value == proof['result']['receipt']['state'] == 'completed_verified'
    app = restart(env)
    response = await app.handle_reconcile(Request())
    assert response.status == 200
    assert app.store.get_request('r')['result'] == proof['result']
    assert app.task_owner.store.get_task(opened[0]).state.value == 'completed_verified'
    assert env.runtime.calls == 1
    events = app.event_bus.get_replay_events('s')
    assert len([e for e in events if e.event == 'task.updated' and e.data['task']['state'] == 'completed_verified']) == 1
    assert len([e for e in events if e.event == 'turn.reconciled']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('hook', ['presence', 'world_claim'])
async def test_postcommit_display_failure_cannot_downgrade_card_or_receipt(env, monkeypatch, tmp_path, hook):
    opened = real_card(env, monkeypatch, tmp_path)
    if hook == 'presence':
        original = env.app._present
        def present(session, state, **fields):
            if fields.get('status') == 'completed_verified':
                raise RuntimeError('scripted postcommit display failure')
            return original(session, state, **fields)
        monkeypatch.setattr(env.app, '_present', present)
    else:
        def fail(*args, **kwargs):
            raise RuntimeError('scripted postcommit claim failure')
        monkeypatch.setattr(env.app, '_world_claim', fail)
    await execute(env)
    proof = env.store.owner_request_receipt('r')
    assert proof['status'] == 'completed'
    assert proof['result'] == env.store.get_request('r')['result']
    assert env.store.get_request('r')['status'] == 'completed'
    assert env.app.task_owner.store.get_task(opened[0]).state.value == 'completed_verified'
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_producer_refuses_current_legacy_run_owner_before_effects(env):
    def legacy_binding(run_id, kwargs):
        env.store.admit_request('legacy', 'legacy work', request_id='legacy')
        env.store.bind_native('legacy', native_run_id=run_id, native_session='owner:legacy')
    env.runtime.before_bind = legacy_binding
    await execute(env)
    assert env.runtime.calls == 0
    assert env.store.get_request('r')['status'] == 'execution_unknown'
    assert env.store.get_request('r')['native_run_id'] is None
    assert env.store.owner_request_receipt('r') is None
    assert env.store.get_request('legacy')['status'] == 'running'


@pytest.mark.asyncio
async def test_projection_keyerror_cannot_publish_legacy_success(env, monkeypatch):
    def fail(*args, **kwargs):
        raise KeyError('scripted storage failure after snapshot')
    monkeypatch.setattr(env.store, 'complete_request', fail)
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        await execute(env)
    assert env.store.owner_request_receipt('r') is not None
    assert not [m for m in env.store.get_session('s')['messages'] if m['role'] == 'assistant']
    assert not any(e.event == 'turn.finish' for e in env.app.event_bus.get_replay_events('s'))
    assert (await restart(env).handle_reconcile(Request())).status == 200
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_legacy_binding_cannot_steal_journal_run(env):
    await execute(env)
    env.store.admit_request('legacy', 'legacy', request_id='legacy')
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        env.store.bind_native('legacy', native_run_id=env.runtime.runs[-1], native_session='owner:legacy')
    assert env.store.get_request('legacy')['native_run_id'] is None


@pytest.mark.asyncio
async def test_foreign_card_cannot_be_finalized_or_cleaned_up_by_request(env, monkeypatch, tmp_path):
    opened = real_card(env, monkeypatch, tmp_path)
    original = env.app._commit_owner_outcome
    def foreign(*args, **kwargs):
        env.app.task_owner.store.update_task(opened[0], lambda task: task.provenance.update(request_id='foreign'))
        return original(*args, **kwargs)
    monkeypatch.setattr(env.app, '_commit_owner_outcome', foreign)
    await execute(env)
    assert env.store.get_request('r')['status'] == 'execution_unknown'
    assert env.store.owner_request_receipt('r') is None
    assert env.app.task_owner.store.get_task(opened[0]).state.value == 'queued'


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [{'_prompt': 'Create output.txt', 'allowed_tools': ['write_file']}], indirect=True)
async def test_actual_foreground_card_path_keeps_durable_inner_run_active_and_recovers(env, monkeypatch, tmp_path):
    from jaeger_ai.core.entity.executive import CognitiveStrategy
    env.runtime.identity = SimpleNamespace(entity_id='test', display_name='Test')
    env.runtime.executive_selector = SimpleNamespace(select_strategy=lambda *args: SimpleNamespace(
        strategy=CognitiveStrategy.REACT_LOOP, complexity_score=0.5, requires_work_ledger=False))
    env.runtime.current_state = SimpleNamespace()
    # Use real prepare/open-card/continuation/task_scope/close-card path. The
    # model port alone writes a disposable artifact through the real ledger.
    def artifact(run_id):
        SqliteEffectLedger().once('artifact-write', 'write_file',
                                 lambda: (tmp_path / 'output.txt').write_text('verified output'), run_id=run_id)
        from jaeger_ai.core.runtime.work_ledger import complete_task, work_ledger
        assert work_ledger(action='create', task_name='Create output', total_items=1,
                           completed_ids=['output'], remaining_count=0,
                           verify={'kind': 'paths_exist', 'paths': [str(tmp_path / 'output.txt')]})['ok']
        assert complete_task(summary='Finished answer.', evidence='Checked the produced file')['ok']
    env.runtime.before_answer = artifact
    # The actual instance workspace is used by the verifier when no explicit
    # workspace was selected at admission.
    from jaeger_agent.core import workspace
    monkeypatch.setattr(workspace, 'get_effective_workspace_dir', lambda: tmp_path)
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    assert SqliteRunStore().get(env.runtime.runs[-1]).state == 'active'
    proof = env.store.owner_request_receipt('r')
    assert proof is not None
    assert proof['result']['receipt']['state'] == 'completed_verified'
    assert env.runtime.observed_authority == [('agent:test', frozenset({'write_file'}))]
    assert (await restart(env).handle_reconcile(Request())).status == 200
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_startup_projects_only_sealed_matching_results_once_without_dispatch(env, monkeypatch):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    env.store.enqueue_request('s', 'queued', request_id='queued')
    env.row = env.store.admit_request('drift-session', 'hello', request_id='drift')
    env.runtime.answers = [('Second answer.', None)]
    with pytest.raises(Crash):
        await execute(env)
    assert env.store.owner_request_receipt('drift') is not None
    with env.store._immediate() as conn:
        conn.execute("UPDATE client_requests SET digest='changed' WHERE request_id='drift'")
    env.store.admit_request('legacy-session', 'legacy', request_id='legacy')
    env.store.bind_native('legacy', native_run_id='legacy-run', native_session='owner:legacy-session')
    app = restart(env)
    app._owner_receipt_lease = app.store.claim_process()
    started = []
    monkeypatch.setattr(app, '_start_admitted_turn', lambda *args: started.append(args))
    assert app._recover_sealed_owner_results() == 1
    assert app.store.get_request('r')['status'] == 'completed'
    assert app.store.get_request('drift')['status'] == 'execution_unknown'
    assert app.store.get_request('legacy')['status'] == 'execution_unknown'
    assert app.store.get_request('queued')['status'] == 'queued'
    assert started == [] and env.runtime.calls == 2
    events = app.event_bus.get_replay_events('s')
    assert app._recover_sealed_owner_results() == 0
    assert app.event_bus.get_replay_events('s') == events
    assert len([m for m in app.store.get_session('s')['messages'] if m['role'] == 'assistant']) == 1
    # The existing end-of-startup drain remains the only queue dispatcher.
    app._drain_all_queues()
    assert len(started) == 1


@pytest.mark.asyncio
async def test_live_projection_failure_marks_recovery_pending_then_startup_projects(env, monkeypatch):
    original = env.store.complete_request
    def fail(*args, **kwargs):
        raise OSError('scripted projection storage failure')
    monkeypatch.setattr(env.store, 'complete_request', fail)
    with pytest.raises(OSError):
        await execute(env)
    row = env.store.get_request('r')
    proof = env.store.owner_request_receipt('r')
    assert row['status'] == 'execution_unknown'
    assert row['result']['owner_result_pending_projection'] is True
    assert 'committed owner result' in row['result']['error']
    assert env.store.get_session('s')['status'] == 'execution_unknown'
    assert proof['status'] == 'completed'
    assert len([e for e in env.app.event_bus.get_replay_events('s') if e.event == 'turn.unknown'
                and e.data.get('owner_result_pending_projection')]) == 1
    monkeypatch.setattr(env.store, 'complete_request', original)
    app = restart(env)
    app._owner_receipt_lease = app.store.claim_process()
    assert app._recover_sealed_owner_results() == 1
    assert app.store.get_request('r')['result'] == proof['result']
    assert env.runtime.calls == 1


@pytest.mark.asyncio
async def test_startup_and_pending_marker_preserve_newer_session_and_reject_stale_lease(env, monkeypatch):
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    app = restart(env)
    app.store.admit_request('s', 'newer', request_id='newer')
    app.store.complete_request('newer', status='failed', result={'error': 'newer failure'})
    app.store.mark_owner_projection_pending('r', app.store.process_lease())
    assert app.store.get_session('s')['status'] == 'failed'
    app._owner_receipt_lease = app.store.claim_process()
    app.store.claim_process()
    with pytest.raises(owner_receipts.OwnerReceiptConflict):
        app._recover_sealed_owner_results()
    app._owner_receipt_lease = app.store.claim_process()
    assert app._recover_sealed_owner_results() == 1
    assert app.store.get_session('s')['status'] == 'failed'
    assert app.store.get_request('newer')['status'] == 'failed'


def configure_actual_owner(env):
    from jaeger_ai.core.entity.executive import CognitiveStrategy
    env.runtime.identity = SimpleNamespace(entity_id='test', display_name='Test')
    env.runtime.executive_selector = SimpleNamespace(select_strategy=lambda *args: SimpleNamespace(
        strategy=CognitiveStrategy.REACT_LOOP, complexity_score=0.5, requires_work_ledger=False))
    env.runtime.current_state = SimpleNamespace()


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [{'_prompt': 'Inspect this project', '_workspace': True, 'interaction_tier': 'agent'}], indirect=True)
async def test_real_yielded_journal_preserves_canonical_durable_run_transfer(env, tmp_path, monkeypatch):
    configure_actual_owner(env)
    env.runtime.answers = [("I'll check that next.", None)] * 5
    await execute(env)
    original = env.store.get_request('r')
    assert original['status'] == 'completed' and original['result']['halt_reason'] == 'yielded'
    assert env.store.owner_request_receipt('r') is None
    task = env.app.task_owner.store.get_task('turn:r')
    assert task.state.value == 'paused' and task.payload['foreground_resume_version'] == 1
    env.app.task_owner._transfer_foreground(task)
    task = env.app.task_owner.store.get_task(task.task_id)
    assert task.state.value == 'queued' and not task.provenance['turn_owned']
    env.runtime.answers = [('Finished continuation.', None)]
    def complete(run_id):
        from jaeger_ai.core.runtime.work_ledger import complete_task, work_ledger
        path = tmp_path / 'continuation.txt'
        SqliteEffectLedger().once('continued-write', 'write_file', lambda: path.write_text('complete'), run_id=run_id)
        assert work_ledger(action='create', task_name='Continuation', total_items=1, completed_ids=['file'], remaining_count=0,
                           verify={'kind': 'paths_exist', 'paths': [str(path)]})['ok']
        assert complete_task(summary='Finished continuation.', evidence='File checked')['ok']
    env.runtime.before_answer = complete
    await env.app.task_owner._execute(task.task_id)
    child = env.store.get_request('turn:r:0')
    assert child['native_run_id'] == original['native_run_id']
    assert child['status'] == 'completed'
    assert env.app.task_owner.store.get_task(task.task_id).state.value == 'completed_verified'
    assert env.store.owner_request_receipt('r') is None  # Never retroactively seal a transferred source.
    assert env.runtime.calls == 6


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [{'_prompt': 'Inspect this project', '_workspace': True, 'interaction_tier': 'agent'}], indirect=True)
@pytest.mark.parametrize('drift', ['lease', 'authority', 'domain', 'last_run', 'child_unknown', 'child_cancelled', 'child_completed', 'child_scope_cancelled'])
async def test_transfer_reuse_rejects_source_drift_and_late_child_callbacks(env, drift):
    configure_actual_owner(env)
    env.runtime.answers = [("I'll check that next.", None)] * 5
    await execute(env)
    task = env.app.task_owner.store.get_task('turn:r')
    env.app.task_owner._transfer_foreground(task)
    dispatched = []
    env.app._start_admitted_turn = lambda row, *args: dispatched.append(row)
    await env.app.task_owner._execute(task.task_id)
    assert len(dispatched) == 1
    child = env.store.get_request('turn:r:0')
    run_id = child['native_run_id']
    if drift == 'lease':
        env.store.claim_process()
    elif drift == 'authority':
        with env.store._immediate() as conn:
            conn.execute("UPDATE client_requests SET digest='changed' WHERE request_id='r'")
    elif drift == 'domain':
        with env.store._immediate() as conn:
            conn.execute("UPDATE client_requests SET native_session='owner:foreign' WHERE request_id='r'")
    elif drift == 'last_run':
        with env.store._immediate() as conn:
            runs = json.loads(journal(env)['native_runs_json'])
            conn.execute('UPDATE owner_request_journal SET native_runs_json=? WHERE request_id=?', (json.dumps(runs + ['later']), 'r'))
    elif drift == 'child_scope_cancelled':
        env.app._cancellations.cancel(child['request_id'])
    else:
        state = {'child_unknown': 'execution_unknown', 'child_cancelled': 'cancelling', 'child_completed': 'completed'}[drift]
        env.store.mark_request_status(child['request_id'], state)
    with pytest.raises((owner_receipts.OwnerReceiptConflict, ValueError)):
        env.app._bind_owner_run(child['request_id'], child['session_id'], run_id, None, task_id=task.task_id)
    assert env.runtime.calls == 5
    if drift == 'child_unknown':
        env.store.enqueue_request(child['session_id'], 'queued follow-up', request_id='late-queued')
        env.row = env.store.get_request(child['request_id'])
        await execute(env)
        assert env.store.get_request(child['request_id'])['status'] == 'execution_unknown'
        assert env.store.get_request('late-queued')['status'] == 'queued'
        assert env.runtime.calls == 5


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [{'_prompt': 'Inspect this project', '_workspace': True, 'interaction_tier': 'agent'}], indirect=True)
async def test_sequential_real_foreground_tasks_do_not_share_sealed_native_ownership(env, tmp_path):
    configure_actual_owner(env)
    def complete(run_id):
        from jaeger_ai.core.runtime.work_ledger import complete_task, work_ledger
        path = tmp_path / f'{run_id}.txt'
        SqliteEffectLedger().once(run_id + ':file', 'write_file', lambda: path.write_text('done'), run_id=run_id)
        work_ledger(action='create', task_name='Task', total_items=1, completed_ids=['file'], remaining_count=0,
                    verify={'kind': 'paths_exist', 'paths': [str(path)]})
        assert complete_task(summary='Finished task.', evidence='File verified')['ok']
    env.runtime.before_answer = complete
    await execute(env)
    first = env.store.owner_request_receipt('r')
    assert first['result']['task_state'] == 'completed_verified'
    env.row = env.store.admit_request('s', 'Inspect this project again', request_id='second', requested={
        'workspace': str(tmp_path), 'interaction_tier': 'agent', 'model': 'scripted', 'provider': 'scripted',
        'allowed_tools': [], 'caller': 'agent:test'})
    env.runtime.answers = [('Finished second task.', None)]
    await execute(env)
    second = env.store.owner_request_receipt('second')
    assert second['result']['task_state'] == 'completed_verified'
    assert first['native_run_id'] != second['native_run_id']
    def unknown():
        raise RuntimeError('later request pending effect')
    with pytest.raises(RuntimeError):
        SqliteEffectLedger().once('later-unknown', 'scripted', unknown, run_id=second['native_run_id'])
    assert env.store.owner_request_receipt('r') == first
    assert env.store.get_request('r')['status'] == 'completed'


@pytest.mark.asyncio
@pytest.mark.parametrize('pending', [False, True])
async def test_returned_interrupted_continuation_qualifies_all_effects(env, pending):
    env.runtime.answers = [("I'll check that next.", None), ('Interrupted.', 'interrupted')]
    def effect_and_cancel(run_id):
        if env.runtime.calls == 1:
            def effect():
                if pending:
                    raise RuntimeError('Earlier effect remains unknown')
                return 'done'
            try:
                SqliteEffectLedger().once('cancel-effect', 'scripted', effect, run_id=run_id)
            except RuntimeError:
                pass
        else:
            env.app._cancellations.cancel('r')
            env.store.mark_request_status('r', 'cancelling')
    env.runtime.before_answer = effect_and_cancel
    await execute(env)
    assert env.runtime.returned.is_set() and len(set(env.runtime.runs)) == 2
    proof = env.store.owner_request_receipt('r')
    assert env.store.get_request('r')['status'] == ('execution_unknown' if pending else 'cancelled')
    if pending:
        assert proof is None
    else:
        assert proof['status'] == 'cancelled' and proof['result']['output'] is None
        assert proof['native_run_ids'] == env.runtime.runs
        assert proof['effects_settled'] and not proof['execution_unknown']
        assert (await restart(env).handle_reconcile(Request())).status == 200
        assert env.runtime.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('conflict', ['lease', 'identity', 'exception'])
async def test_cancelled_return_never_relaxes_producer_fences(env, conflict):
    env.runtime.answers = [('Interrupted.', 'interrupted')]
    def interfere(run_id):
        env.app._cancellations.cancel('r')
        env.store.mark_request_status('r', 'cancelling')
        if conflict == 'lease':
            env.store.claim_process()
        elif conflict == 'identity':
            with env.store._immediate() as conn:
                conn.execute("UPDATE client_requests SET digest='foreign' WHERE request_id='r'")
        else:
            raise RuntimeError('Worker raised rather than returning')
    env.runtime.before_answer = interfere
    await execute(env)
    assert journal(env)['terminal_json'] is None
    assert env.store.get_request('r')['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_returned_cancel_card_and_proof_atomic_before_projection_crash(env, monkeypatch, tmp_path):
    opened = real_card(env, monkeypatch, tmp_path)
    env.runtime.answers = [('Interrupted.', 'interrupted')]
    def cancel(run_id):
        env.app._cancellations.cancel('r')
        env.store.mark_request_status('r', 'cancelling')
    env.runtime.before_answer = cancel
    def crash(*args, **kwargs):
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', crash)
    with pytest.raises(Crash):
        await execute(env)
    proof = env.store.owner_request_receipt('r')
    assert proof['status'] == proof['result']['receipt']['state'] == 'cancelled'
    assert env.app.task_owner.store.get_task(opened[0]).state.value == 'cancelled'
    app = restart(env)
    assert (await app.handle_reconcile(Request())).status == 200
    assert (await app.handle_reconcile(Request())).status == 200
    assert json.loads((await app.handle_cancel_turn(Request())).text)['already_terminal']
    assert app.store.owner_request_receipt('r') == proof
    events = app.event_bus.get_replay_events('s')
    assert len([e for e in events if e.event == 'task.updated' and e.data['task']['state'] == 'cancelled']) == 1
    assert len([e for e in events if e.event == 'turn.reconciled']) == 1
    assert app.store.get_request('r')['status'] == 'cancelled'
    assert env.runtime.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('env', [{'_prompt': 'Inspect this project', '_workspace': True, 'interaction_tier': 'agent'}], indirect=True)
@pytest.mark.parametrize('pending_child', [False, True])
async def test_real_foreground_cancel_handler_requires_return_and_children(env, monkeypatch, pending_child):
    env.runtime.identity = SimpleNamespace(entity_id='test', display_name='Test')
    entered, release = threading.Event(), threading.Event()
    env.runtime.answers = [('Interrupted.', 'interrupted')]
    def block(run_id):
        entered.set()
        assert release.wait(5)
    env.runtime.before_answer = block
    task = asyncio.create_task(execute(env))
    env.app._running_tasks['r'] = task
    started = []
    monkeypatch.setattr(env.app, '_drain_session_queue', lambda session: started.append(session))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        response = await env.app.handle_cancel_turn(Request())
        assert json.loads(response.text)['cancel_requested']
        card = env.app.task_owner.store.get_task('turn:r')
        assert card.cancellation and card.state.value == 'paused'
        assert env.store.owner_request_receipt('r') is None
        if pending_child:
            env.app.task_owner.store.update_task('turn:r', lambda card: card.payload.update(
                cancellation_children=[{'handoff_id': 'child', 'outcome': 'unknown'}]))
        release.set()
        await task
    finally:
        release.set()
        await asyncio.to_thread(env.runtime.returned.wait, 5)
    card = env.app.task_owner.store.get_task('turn:r')
    assert card.state.value == ('paused' if pending_child else 'cancelled')
    assert env.store.get_request('r')['status'] == ('execution_unknown' if pending_child else 'cancelled')
    assert bool(env.store.owner_request_receipt('r')) is not pending_child
    if pending_child:
        assert not started
        assert not [e for e in env.app.event_bus.get_replay_events('s') if e.event == 'turn.cancelled']
