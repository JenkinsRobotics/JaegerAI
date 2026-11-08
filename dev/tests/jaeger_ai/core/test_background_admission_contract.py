"""New client default-lead task authority is frozen before asynchronous dispatch."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from jaeger_ai.core.gateway.event_bus import GatewayEventBus
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.tasks.owner import GatewayTaskOwner, TaskAdmissionChanged
from jaeger_ai.core.tasks.research import RESEARCH_CONTRACT


@pytest.fixture
def owner(tmp_path, monkeypatch):
    from jaeger_ai.core.agent_registry.specialists import LEAD_AGENT_ID
    from jaeger_ai.core.gateway import owner_receipts
    identity = {'id': LEAD_AGENT_ID, 'kind': 'jaeger_native', 'role': 'lead', 'disabled': False}
    monkeypatch.setattr(owner_receipts, 'session_agent_identity', lambda sid, meta: deepcopy(identity))
    store = GatewaySessionStore(tmp_path/'gateway.sqlite3')
    store.ensure_session('parent', metadata={'agent_id': LEAD_AGENT_ID, 'agent_pinned': True})
    defaults = {'workspace': str(tmp_path/'workspace'), 'model': 'contract-model',
                'provider': 'openai', 'route_fingerprint': 'route-v1'}
    gateway = SimpleNamespace(store=store, event_bus=GatewayEventBus(store=store),
        _running_tasks={}, _cancellations=SimpleNamespace(is_cancelled=lambda rid: False),
        _foreground_execution_defaults=lambda: deepcopy(defaults), _current_tier=lambda: 'jaeger',
        _start_admitted_turn=lambda *args: None, _owner_receipt_lease=store.claim_process())
    result = GatewayTaskOwner(gateway)
    result.test_defaults = defaults
    return result


def submit(owner, **kwargs):
    return owner.submit('Research objective', context={'source': 'client', 'session_id': 'parent',
        'client_submission_id': 'once', 'execution': {'caller': 'webui'}},
        research_contract=deepcopy(RESEARCH_CONTRACT), canonical_background=True, **kwargs)['task_id']


def test_default_research_freezes_scope_before_dispatch(owner):
    task = owner.store.get_task(submit(owner))
    execution = task.payload['execution']
    assert execution['model'] == 'contract-model'
    assert execution['provider'] == 'openai'
    assert execution['interaction_tier'] == 'jaeger'
    assert execution['_instance_defaults'] == {'workspace': owner.test_defaults['workspace'], 'route_fingerprint': 'route-v1'}
    assert execution['caller'] == 'webui'
    assert execution['allowed_tools'] is None
    assert task.agent_id
    assert owner.gateway.store.get_session('parent')['workspace'] == ''
    asyncio.run(owner._execute(task.task_id))
    task = owner.store.get_task(task.task_id)
    row = owner.gateway.store.get_request(task.task_id+':0')
    contract = task.payload['background_admissions'][row['request_id']]
    assert contract['execution'] == row['execution']
    assert contract['input_text'] == row['input_text']
    assert contract['research_contract'] == RESEARCH_CONTRACT
    assert contract['research_artifacts'] == task.payload['research_artifacts']
    assert not owner.gateway.store.has_owner_request_journal(row['request_id'])


@pytest.mark.parametrize('field', ['input_text', 'execution', 'request_id', 'session_id'])
def test_foreign_terminal_receipt_is_rejected(owner, field):
    tid = submit(owner)
    asyncio.run(owner._execute(tid))
    task = owner.store.get_task(tid)
    row = owner.gateway.store.get_request(tid+':0')
    row['status'] = 'completed'
    row[field] = {} if field == 'execution' else 'foreign'
    assert owner._continuation_receipt_error(task, row)


@pytest.mark.parametrize('field', ['goal', 'agent_id', 'execution', 'research_contract', 'research_artifacts'])
def test_task_drift_blocks_admission(owner, field):
    tid = submit(owner)
    original = owner.store.get_task(tid)
    def change(task):
        if field in {'goal', 'agent_id'}:
            setattr(task, field, 'foreign')
        else:
            task.payload[field] = {'foreign': True}
    owner.store.update_task(tid, change)
    with owner.gateway.store._immediate() as conn, pytest.raises(TaskAdmissionChanged):
        owner._admission_guard(conn, original)


def test_default_route_drift_blocks_approval(owner):
    tid = submit(owner, proposal=True)
    owner.test_defaults['route_fingerprint'] = 'changed'
    with pytest.raises(ValueError):
        owner.resolve(tid, True)
    assert not owner.store.get_task(tid).provenance['authorized']


def test_replay_and_edited_proposal_keep_research_namespace(owner):
    tid = submit(owner, proposal=True)
    first = owner.store.get_task(tid)
    edited = owner.edit_proposal(tid, goal='Edited research', expected_updated_at=first.updated_at)
    assert submit(owner, proposal=True) == tid
    owner.resolve(tid, True)
    asyncio.run(owner._execute(tid))
    task = owner.store.get_task(tid)
    assert task.goal == 'Edited research'
    assert task.payload['research_artifacts'] == first.payload['research_artifacts']
    assert task.payload['research_contract'] == RESEARCH_CONTRACT
    assert 'Edited research' in owner.gateway.store.get_request(tid+':0')['input_text']


@pytest.mark.parametrize('change', ['route', 'workspace', 'agent', 'tier', 'revoke', 'cancel', 'attempt', 'session', 'mode', 'actionable', 'parent'])
def test_dispatch_rechecks_durable_authority(owner, monkeypatch, change):
    tid = submit(owner)
    asyncio.run(owner._execute(tid))
    row = owner.gateway.store.get_request(tid+':0')
    if change == 'route':
        owner.test_defaults['route_fingerprint'] = 'changed'
    elif change == 'workspace':
        owner.test_defaults['workspace'] += '/changed'
    elif change == 'agent':
        monkeypatch.setattr('jaeger_ai.core.tasks.background_admission.session_agent_identity', lambda *args: None)
    elif change == 'tier':
        owner.gateway._current_tier = lambda: 'agent'
    elif change in {'mode', 'actionable', 'parent'}:
        key, value = {'mode': ('execution_mode', 'text_only'), 'actionable': ('actionable', False),
                      'parent': ('parent_session_id', 'foreign')}[change]
        owner.gateway.store.ensure_session('task:'+tid, metadata={key: value})
    elif change == 'session':
        owner.gateway.store.ensure_session('task:'+tid, metadata={'agent_id': 'foreign'})
    else:
        def mutate(task):
            if change == 'revoke': task.provenance['authorized'] = False
            if change == 'cancel': task.cancellation = 'Stopped'
            if change == 'attempt': task.payload['attempt'] = 1
        owner.store.update_task(tid, mutate)
    with owner.gateway.store._get_conn() as conn, pytest.raises(ValueError):
        owner.background_dispatch_guard(conn, row)


def test_native_binding_is_exact_and_transactional(owner, monkeypatch):
    import os
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    tid = submit(owner)
    asyncio.run(owner._execute(tid))
    monkeypatch.setattr(SqliteRunStore, 'get', lambda self, native: SimpleNamespace(owner_pid=os.getpid(), state='active'))
    # Bind a producer-created identity through the owner guard, never options alone.
    sid, rid = 'task:'+tid, tid+':0'
    bound = owner.gateway.store.bind_native(rid, native_run_id='own-run', native_session='owner:'+sid,
        native_binding_guard=owner.background_binding_guard)
    task = owner.store.get_task(tid)
    assert not owner._continuation_receipt_error(task, bound)
    foreign = {**bound, 'native_run_id': 'foreign'}
    assert owner._continuation_receipt_error(task, foreign)
    with pytest.raises(ValueError):
        owner.gateway.store.bind_native(rid, native_run_id='foreign', native_session='owner:'+sid,
            native_binding_guard=owner.background_binding_guard)
    assert owner.gateway.store.get_request(rid)['native_run_id'] == 'own-run'


def test_historical_and_explicit_provider_tasks_are_not_upgraded(owner):
    ctx = {'source': 'client', 'session_id': 'parent', 'execution': {'model': 'explicit', 'provider': 'openai'}}
    tid = owner.submit('Explicit', context=ctx, canonical_background=True)['task_id']
    assert 'background_admission_version' not in owner.store.get_task(tid).payload
    tid = owner.submit('Historical', context={**ctx, 'execution': {}})['task_id']
    assert 'background_admission_version' not in owner.store.get_task(tid).payload


def test_transaction_rollback_does_not_leave_attempt_proof(owner):
    tid = submit(owner)
    task = owner.store.get_task(tid)
    original = owner._background_admission_guard
    def fail(conn, task, resolved, prompt):
        original(conn, task, resolved, prompt)
        raise ValueError('injected admission crash')
    owner._background_admission_guard = fail
    with pytest.raises(ValueError, match='injected'):
        asyncio.run(owner._execute(tid))
    assert owner.gateway.store.get_request(tid+':0') is None
    assert not owner.store.get_task(tid).payload.get('background_admissions')


@pytest.mark.parametrize('mode', ['foreign-task', 'unsettled', 'settled'])
def test_native_reuse_requires_same_task_settled_attempt(owner, monkeypatch, mode):
    import os
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
    from jaeger_ai.core.entity.runtime import EntityRuntime
    monkeypatch.setattr(SqliteRunStore, 'get', lambda self, native: SimpleNamespace(owner_pid=os.getpid(), state='completed'))
    monkeypatch.setattr(EntityRuntime, 'run_has_indeterminate_effects', lambda native: mode == 'unsettled')
    tid = submit(owner)
    asyncio.run(owner._execute(tid))
    store = owner.gateway.store
    store.bind_native(tid+':0', native_run_id='original', native_session='owner:task:'+tid,
        native_binding_guard=owner.background_binding_guard)
    store.complete_request(tid+':0', status='completed', result={'output': 'checkpoint', 'halt_reason': 'yielded'})
    def next_attempt(task):
        task.payload['attempt'] = 1
        task.payload['native_run_id'] = 'original'
    owner.store.update_task(tid, next_attempt)
    if mode == 'foreign-task':
        foreign = store.admit_request('unrelated', 'foreign', request_id='foreign')
        store.bind_native('foreign', native_run_id='original', native_session='owner:unrelated')
    if mode == 'settled':
        asyncio.run(owner._execute(tid))
        task = owner.store.get_task(tid)
        row = store.get_request(tid+':1')
        assert not owner._continuation_receipt_error(task, row)
        assert task.payload['background_admissions'][tid+':1']['native_run_id'] == 'original'
    else:
        with pytest.raises(ValueError):
            asyncio.run(owner._execute(tid))
        assert not store.get_request(tid+':1')['native_run_id']


def test_objective_edit_cannot_bless_scope_drift(owner):
    tid = submit(owner, proposal=True)
    def change(task):
        task.payload['execution']['allowed_tools'] = ['foreign-tool']
    changed = owner.store.update_task(tid, change)
    with pytest.raises(ValueError):
        owner.edit_proposal(tid, goal='New objective', expected_updated_at=changed.updated_at)
    assert owner.store.get_task(tid).goal == 'Research objective'


@pytest.mark.parametrize('field', ['execution', 'text', 'session_id', 'turn_id'])
def test_actual_dispatch_arguments_match_frozen_request(owner, field):
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    tid = submit(owner)
    asyncio.run(owner._execute(tid))
    row = owner.gateway.store.get_request(tid+':0')
    gateway = owner.gateway
    gateway.task_owner = owner
    gateway._session_agent_id = lambda session: None
    gateway._resolve_session_agent = lambda sid, **kwargs: None
    gateway._system_prompt_for_agent = lambda agent: ''
    errors = []
    async def capture(*args, **kwargs):
        errors.append(kwargs.get('identity_error'))
    gateway._execute_scoped_turn = capture
    actual = {key: deepcopy(row[key]) for key in ('session_id', 'input_text', 'execution', 'turn_id')}
    if field == 'execution': actual[field]['allowed_tools'] = ['foreign']
    elif field == 'text': actual['input_text'] = 'foreign objective'
    else: actual[field] = 'foreign'
    asyncio.run(JaegerGatewayApp._execute_turn_inner(gateway, actual['session_id'], actual['turn_id'],
        actual['input_text'], request_id=row['request_id'], execution=actual['execution']))
    assert errors and errors[0] is not None
