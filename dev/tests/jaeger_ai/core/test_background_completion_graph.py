"""Independent follow-up probes for corrected lineage and settlement boundaries."""
import os
import json
from copy import deepcopy

import pytest
from jaeger_agent.memory import sqlite_store
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_ai.contract.handoffs import child_request_id
from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
from jaeger_ai.core.gateway.handoff_ownership import child_receipt
from dev.tests.jaeger_ai.core.test_background_terminal_journal import env, journal, crash, restart, pending_effect
from dev.tests.jaeger_ai.core.test_owner_request_journal import Crash


def separate_child(env, parent_native, effect=True):
    sid = 'task:'+env.tid
    actor = env.store.get_request(env.rid)['execution']['caller']
    handoff = env.store.save_handoff({'id':'indirect-child','request_id':'indirect-child-request',
        'from_agent_id':'native:jaeger','to_agent_id':'native:builder','session_id':sid,
        'parent_run_id':parent_native,'task':'Synthetic separately bound child','status':'completed',
        'metadata':{'caller_actor':actor,'parent_binding':{'request_id':env.rid,'session_id':sid,
            'root_actor':actor,'child_actor':actor,'source_agent_id':'native:jaeger'}}})
    csid=specialist_session(handoff['to_agent_id'],handoff['request_id'])
    crid=child_request_id(handoff['request_id'])
    env.store.ensure_session(csid,metadata={'handoff_id':handoff['id'],'agent_id':handoff['to_agent_id'],'parent_session_id':sid})
    env.store.admit_request(csid,'Synthetic child result',request_id=crid,
        requested={'caller':actor,'is_subordinate':True,'model':'scripted','provider':'openai'})
    c=SqliteCommitmentStore().create('Separate native child',kind='delegation')
    run=SqliteRunStore().create(c.id,owner_pid=os.getpid(),relation='root')
    SqliteRunStore().transition(run.id,'active')
    SqliteRunStore().checkpoint(run.id,{'separate_child':True})
    env.store.bind_native(crid,native_run_id=run.id,native_session='owner:'+csid)
    if effect: pending_effect(run.id)
    else: SqliteRunStore().transition(run.id,'completed')
    env.store.complete_request(crid,status='completed',result={'status':'completed','output':'Retained child result'})
    assert child_receipt(env.app,handoff)[3] is True
    return run.id


@pytest.mark.asyncio
@pytest.mark.parametrize('effect',[False,True])
async def test_gateway_child_native_receipt_cannot_hide_pending_effect(env,effect):
    produce=env.runtime.before_answer
    env.runtime.before_answer=lambda native:(separate_child(env,native,effect),produce(native))
    await env.app.task_owner._execute(env.tid)
    assert not journal(env)['terminal_json']
    assert env.app.task_owner.store.get_task(env.tid).state.value == ('paused' if effect else 'completed_verified')


async def first_rotation(env):
    roots=[]
    def first(native):
        if not roots:
            roots.append(native)
            SqliteRunStore().transition(native,'completed')
    env.runtime.before_answer=first
    env.runtime.answers=[('First run returned, continue',None),('Partial progress','yielded')]
    await env.app.task_owner._execute(env.tid)
    task=env.app.task_owner.store.get_task(env.tid)
    assert task.payload['attempt']==1
    assert len(task.payload['background_admissions'][env.rid]['native_run_ids'])==2
    return roots[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['prior-map-missing','prior-list-truncated','prior-row-missing'])
async def test_incomplete_retained_ancestry_never_becomes_empty_tree(env,fault):
    produce=env.runtime.before_answer
    earlier=await first_rotation(env)
    old_rid=env.rid
    env.store.save_handoff({'id':'old-child','from_agent_id':'native:jaeger','to_agent_id':'native:builder',
        'parent_run_id':earlier,'task':'Retained older native child','status':'completed'})
    def truncate_and_finish(native):
        def change(task):
            if fault=='prior-map-missing': task.payload['background_admissions'].pop(old_rid)
            if fault=='prior-list-truncated': task.payload['background_admissions'][old_rid]['native_run_ids'].remove(earlier)
        if fault=='prior-row-missing':
            with env.store._immediate() as conn:
                conn.execute('DELETE FROM client_requests WHERE request_id=?',(old_rid,))
        else:
            env.app.task_owner.store.update_task(env.tid,change)
        produce(native)
    env.runtime.before_answer=truncate_and_finish
    env.runtime.answers=[('Finished answer.',None)]
    await env.app.task_owner._execute(env.tid)
    env.rid=env.tid+':1'
    assert journal(env)['terminal_json'] is None, 'Incomplete prior admission silently discarded retained child ancestry'


@pytest.mark.asyncio
@pytest.mark.parametrize('state',['waiting_for_approval','failed','blocked'])
async def test_accepted_native_lifecycle_change_after_projection_is_not_verified(env,monkeypatch,state):
    produce = env.runtime.before_answer
    env.runtime.before_answer = lambda native: (separate_child(env, native, False), produce(native))
    persist=env.app._persist_terminal
    def after_projection(*args,**kwargs):
        persist(*args,**kwargs)
        native=env.store.get_request(env.rid)['native_run_id']
        SqliteRunStore().transition(native,state,wake_key='synthetic-approval' if state=='waiting_for_approval' else None)
    monkeypatch.setattr(env.app,'_persist_terminal',after_projection)
    await env.app.task_owner._execute(env.tid)
    assert env.store.get_request(env.rid)['status']=='completed'
    assert env.app.task_owner.store.get_task(env.tid).state.value!='completed_verified'


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', [None, 'child', 'earlier'])
async def test_no_journal_upgrade_veto_never_creates_recovery_authority(env, monkeypatch, fault):
    produce = env.runtime.before_answer
    earlier = await first_rotation(env) if fault == 'earlier' else None
    if earlier:
        env.rid = env.tid+':1'
    env.runtime.before_answer = produce
    env.runtime.answers = [('Finished answer.', None)]
    persist = env.app._persist_terminal
    def stop_before_settlement(*args, **kwargs):
        persist(*args, **kwargs)
        raise Crash()
    monkeypatch.setattr(env.app, '_persist_terminal', stop_before_settlement)
    with pytest.raises(Crash):
        await env.app.task_owner._execute(env.tid)
    if fault == 'child':
        separate_child(env, env.store.get_request(env.rid)['native_run_id'])
    elif earlier:
        pending_effect(earlier)
    calls = env.runtime.calls
    # Synthetic schema17 migration fixture. Independent verification also uses
    # actual ccda0c-produced databases, not these downgraded test databases.
    with env.store._immediate() as conn:
        conn.execute('DROP TABLE background_request_journal')
        conn.execute('DROP TABLE background_native_enrollments')
        conn.execute("UPDATE schema_meta SET value='17' WHERE key='version'")
    app = restart(env)
    monkeypatch.setattr(app, '_foreground_execution_defaults', env.app._foreground_execution_defaults)
    monkeypatch.setattr(app, '_current_tier', lambda: 'jaeger')
    monkeypatch.setattr(app, '_schedule_summary', lambda sid: None)
    monkeypatch.setattr(app, '_start_admitted_turn', lambda *a, **k: pytest.fail('No upgrade dispatch'))
    assert app._recover_sealed_owner_results() == 0
    await app.task_owner._execute(env.tid)
    assert app.task_owner.store.get_task(env.tid).state.value == ('completed_verified' if fault is None else 'paused')
    with app.store._get_conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM background_request_journal').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM background_native_enrollments').fetchone()[0] == 0
    assert env.runtime.calls == calls


@pytest.mark.asyncio
@pytest.mark.parametrize('remove_request', [False, True])
@pytest.mark.parametrize('receiver', ['foreground', 'unmarked', 'foreign-task'])
async def test_producer_enrollment_protects_truncated_older_native_from_foreign_bind(env, remove_request, receiver):
    from jaeger_ai.core.gateway.session_store import RequestConflict
    from jaeger_ai.core.gateway.owner_receipts import protected_background_sources, begin
    native = await first_rotation(env)
    prior = env.rid
    env.app.task_owner.store.update_task(env.tid,
        lambda task: task.payload['background_admissions'][prior]['native_run_ids'].remove(native))
    if remove_request:
        with env.store._immediate() as conn:
            conn.execute('DELETE FROM client_requests WHERE request_id=?', (prior,))
    with env.store._get_conn() as conn:
        assert (env.tid, prior) in protected_background_sources(conn, native)
    sid = 'task:foreign' if receiver == 'foreign-task' else 'foreign'
    env.store.admit_request(sid, 'Foreign request', request_id='foreign', requested={'model':'scripted','provider':'openai'})
    token = begin(env.store, 'foreign', sid, env.app._owner_receipt_lease) if receiver == 'foreground' else None
    with pytest.raises(RequestConflict, match='protected background'):
        env.store.bind_native('foreign', native_run_id=native, native_session='owner:'+sid, owner_receipt_token=token, native_binding_guard=env.app.task_owner.background_binding_guard)
    assert env.store.get_request('foreign')['native_run_id'] is None


@pytest.mark.asyncio
async def test_native_transition_failure_precedes_task_completion_publication(env, monkeypatch):
    produce = env.runtime.before_answer
    env.runtime.before_answer = lambda native: (separate_child(env, native, False), produce(native))
    transition = SqliteRunStore.transition
    persist = env.app._persist_terminal
    def fail_completion(self, ident, state, **kwargs):
        if state == 'completed':
            raise RuntimeError('Synthetic lifecycle settlement failure')
        return transition(self, ident, state, **kwargs)
    def project(*args, **kwargs):
        persist(*args, **kwargs)
        monkeypatch.setattr(SqliteRunStore, 'transition', fail_completion)
    monkeypatch.setattr(env.app, '_persist_terminal', project)
    await env.app.task_owner._execute(env.tid)
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'paused'
    assert not env.app.task_owner.store.get_task(env.tid).payload.get('delivered')


@pytest.mark.asyncio
async def test_schema18_journal_is_not_backfilled_as_native_enrollment(env, monkeypatch):
    await crash(env, monkeypatch)
    with env.store._immediate() as conn:
        conn.execute('DROP TABLE background_native_enrollments')
        conn.execute("UPDATE schema_meta SET value='18' WHERE key='version'")
    app = restart(env)
    assert app._recover_sealed_owner_results() == 0
    with app.store._get_conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM background_native_enrollments').fetchone()[0] == 0
    assert app.store.get_request(env.rid)['status'] == 'execution_unknown'


@pytest.mark.asyncio
async def test_prior_capture_drift_blocks_prebind_before_another_producer(env):
    native = await first_rotation(env)
    prior, calls = env.rid, env.runtime.calls
    env.app.task_owner.store.update_task(env.tid,
        lambda task: task.payload['background_admissions'][prior]['native_run_ids'].remove(native))
    await env.app.task_owner._execute(env.tid)
    assert env.app.task_owner.store.get_task(env.tid).state.value == 'paused'
    assert env.runtime.calls == calls
