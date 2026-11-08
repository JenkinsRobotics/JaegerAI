"""Foreground slice ownership transfers only from qualified canonical receipts."""
import asyncio
import pytest
from dev.tests.jaeger_ai.core.test_gateway_turn_card import env, REQUEST
from jaeger_ai.core.tasks.models import TaskState

async def run(env, rid='foreground', tools=None, attachments=False):
    choices={'workspace':str(env.workspace), 'model':'test-model', 'provider':'test-provider', 'caller':'human:operator',
             'allowed_tools': tools, 'interaction_tier':'agent'}
    admitted=env.app.store.admit_request('s',REQUEST,request_id=rid,requested=choices)
    execution=admitted['execution']
    env.app._continued_owner_react=lambda *a,**kw: {'text':'Partial work', 'halt_reason':'yielded'}
    await env.app._execute_turn('s',admitted['turn_id'],REQUEST,request_id=rid,execution=execution)
    return env.app.store.get_request(rid)

@pytest.mark.asyncio
@pytest.mark.parametrize('tools',[[],['read_file']])
async def test_new_card_freezes_execution_and_waits_for_receipt(env,tools):
    row=await run(env,tools=tools)
    task=env.app.task_owner.store.get_task('turn:foreground')
    assert task.state==TaskState.PAUSED
    assert task.payload['execution']==row['execution']
    assert task.payload['foreground_resume_version']==1
    assert task.payload['original_request_id']=='foreground'
    assert task.result=='Partial work'
    # A synthetic worker without a native trajectory is not resumable.
    await env.app.task_owner.tick()
    task=env.app.task_owner.store.get_task(task.task_id)
    assert task.state==TaskState.FAILED
    assert 'checkpoint' in task.error.lower()
    assert len(env.app.store.list_requests())==1

@pytest.mark.asyncio
async def test_historical_card_cannot_be_promoted(env):
    task=env.app.task_owner.open_turn(session_id='s',request_id='legacy',text=REQUEST,
                                   strategy='react_loop',owner='operator',workspace=str(env.workspace))
    env.app.task_owner.close_turn(task.task_id,{'halt_reason':'yielded'},status='completed')
    await env.app.task_owner.tick()
    assert env.app.task_owner.store.get_task(task.task_id).state==TaskState.FAILED
    assert not env.app.task_owner._active

from dev.tests.jaeger_ai.core.test_foreground_transfer_recovery import gateway, seed, drain
from jaeger_ai.core.tasks.owner import TaskAdmissionChanged

def _admit_continuation(gateway,task,*,save_contract=True):
    owner=gateway.task_owner
    sid='task:'+task.task_id
    owner._execution_session(task)
    prompt=owner._continuation_prompt(task)
    execution=owner._continuation_execution(task)
    return gateway.store.admit_request(sid,prompt,
        request_id=task.task_id+':'+str(task.payload.get('attempt',0)),requested=execution,
        admission_guard=(lambda conn:owner._admission_guard(conn,task,execution=execution,prompt=prompt))
                        if save_contract else None)

@pytest.mark.asyncio
@pytest.mark.parametrize('tools',[[],['read_file']])
async def test_competing_ticks_dispatch_one_slice_with_exact_grant(gateway,tools):
    tid,native=seed(gateway,tools=tools)
    before=gateway.store.get_request('foreground')['execution']
    launches=[]
    def finish(admitted,sid,prompt):
        launches.append(admitted['request_id'])
        actual=admitted['execution']
        for key in ('allowed_tools','caller','model','provider','workspace','interaction_tier'):
            assert actual[key]==before[key]
        assert gateway.store.get_request(admitted['request_id'])['native_run_id']==native
        path=gateway.store.path.parent/'result.txt'
        path.write_text('verified result')
        import hashlib
        gateway.store.complete_request(admitted['request_id'],status='completed',result={
            'output':'Verified result', 'task_completion':{'ok':True,'verification_receipts':[
                {'kind':'file_sha256','path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}})
    gateway._start_admitted_turn=finish
    await asyncio.gather(*[gateway.task_owner.tick() for _ in range(4)])
    await drain(gateway.task_owner)
    assert launches==[tid+':0']
    assert len(gateway.task_owner.store.list_tasks())==1
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.COMPLETED_VERIFIED
    assert task.payload['delivered']
    assert [r.run_id for r in task.run_history]==['foreground',tid+':0']

@pytest.mark.asyncio
async def test_stale_wider_snapshot_cannot_admit_after_narrowing(gateway):
    tid,_=seed(gateway)
    await gateway.task_owner.tick()
    stale=gateway.task_owner.store.get_task(tid)
    gateway.task_owner.store.update_task(tid,lambda task: task.payload['execution'].update(allowed_tools=[]))
    with gateway.store._immediate() as conn:
        with pytest.raises(TaskAdmissionChanged,match='authority changed'):
            gateway.task_owner._admission_guard(conn,stale)
    gateway._start_admitted_turn=lambda *a: pytest.fail('Narrowed authority must not dispatch')
    await gateway.task_owner._execute(tid)
    assert len(gateway.store.list_requests())==1

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['revoked','narrowed','original_stop'])
async def test_admitted_but_undispatched_continuation_rechecks_authority(gateway,change):
    tid,_=seed(gateway)
    await gateway.task_owner.tick()
    task=gateway.task_owner.store.get_task(tid)
    sid='task:'+tid
    gateway.task_owner._execution_session(task)
    _admit_continuation(gateway,task)
    if change=='revoked':
        gateway.task_owner.store.update_task(tid,lambda t:t.provenance.update(authorized=False))
    elif change=='narrowed':
        gateway.task_owner.store.update_task(tid,lambda t:t.payload['execution'].update(allowed_tools=[]))
    else:
        gateway._cancellations.cancel('foreground')
    gateway._start_admitted_turn=lambda *a:pytest.fail('Old admission cannot bypass changed authority')
    await gateway.task_owner._execute(tid)
    assert len(gateway.store.list_requests())==2

@pytest.mark.asyncio
@pytest.mark.parametrize('field,value',[('attachments',[{'attachment_id':'old','sha256':'a'*64}]),
    ('attachment_ids',['old']),('model',None),('provider',None),('model','default'),('provider','local'),('interaction_tier',None),('workspace','relative/project')])
async def test_unsupported_inputs_never_transfer(gateway,field,value):
    tid,_=seed(gateway)
    # Simulate a canonical unsupported admission, not a new grant inferred from defaults.
    import json
    execution=gateway.store.get_request('foreground')['execution']
    execution[field]=value
    with gateway.store._immediate() as conn:
        conn.execute('UPDATE client_requests SET execution_json=? WHERE request_id=?',
                     (json.dumps(execution),'foreground'))
    gateway.task_owner.store.update_task(tid,lambda t:t.payload.update(execution=execution))
    gateway._start_admitted_turn=lambda *a:pytest.fail('Unsupported input must not dispatch')
    await drain(gateway.task_owner)
    assert gateway.task_owner.store.get_task(tid).state==TaskState.FAILED
    assert len(gateway.store.list_requests())==1


def test_stable_task_ledger_survives_intervening_chat(env,monkeypatch,tmp_path):
    from types import SimpleNamespace
    from jaeger_ai import main
    from jaeger_ai.core.runtime.work_ledger import ledger_scope,work_ledger,active_ledger,reset
    monkeypatch.setitem(main._pipeline,'layout',SimpleNamespace(root=tmp_path,run_dir=tmp_path/'run'))
    seen=[]
    def step(prompt,**kw):
        ledger=active_ledger()
        if ledger is None:
            work_ledger(action='create',task_name='Original accepted task',total_items=3)
            ledger=active_ledger()
        seen.append(ledger.task_id)
        return {'text':'Partial checkpoint','halt_reason':'hit max_iterations=8 without a final answer'}
    env.app._owner_react_turn=step
    options={'task_id':'turn:stable','turn_owned':True}
    env.app._continued_owner_react(REQUEST,session_key='s',request_id='original',execution={'options':options})
    with ledger_scope('s'):
        other=work_ledger(action='create',task_name='Unrelated parent task',total_items=1)['ledger']['task_id']
    reset() # exercise persisted pointer, not the in-memory ledger cache
    env.app._continued_owner_react(REQUEST,session_key='task:turn:stable',request_id='continuation',
                                  execution={'options':{'task_id':'turn:stable'}})
    assert len(seen)>2 and len(set(seen))==1 and seen[0]!=other


def test_transfer_does_not_gain_background_code_approval(gateway):
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.server import _GatewayToolConfirmationProvider
    tid,_=seed(gateway)
    provider=_GatewayToolConfirmationProvider(gateway,'task:'+tid,tid+':0')
    assert not provider._approved_task_code_step(SimpleNamespace(operation='execute_code'))

@pytest.mark.asyncio
async def test_admission_before_native_binding_restores_same_run(gateway):
    tid,native=seed(gateway)
    await gateway.task_owner.tick()
    task=gateway.task_owner.store.get_task(tid)
    sid='task:'+tid
    gateway.task_owner._execution_session(task)
    admitted=_admit_continuation(gateway,task,save_contract=False)
    assert not admitted.get('native_run_id')
    launches=[]
    def finish(admitted,sid,prompt):
        launches.append(admitted['request_id'])
        assert gateway.store.get_request(admitted['request_id'])['native_run_id']==native
        gateway.store.complete_request(admitted['request_id'],status='completed',result={'halt_reason':'blocked','output':'Retained blocker'})
    gateway._start_admitted_turn=finish
    await gateway.task_owner._execute(tid)
    assert launches==[tid+':0']
    assert gateway.task_owner.store.get_task(tid).state==TaskState.BLOCKED

@pytest.mark.asyncio
async def test_pending_effect_after_transfer_stops_next_admission(gateway):
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    tid,native=seed(gateway)
    await gateway.task_owner.tick()
    def unknown():
        raise RuntimeError('Uncertain synthetic effect')
    with pytest.raises(RuntimeError):
        SqliteEffectLedger().once('late-pending','synthetic',unknown,run_id=native)
    gateway._start_admitted_turn=lambda *a:pytest.fail('Unknown effect cannot be replayed')
    await gateway.task_owner._execute(tid)
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.PAUSED and 'unknown' in task.error
    assert len(gateway.store.list_requests())==1

@pytest.mark.asyncio
async def test_real_controller_yield_hands_same_card_to_gateway_continuation(env,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from jaeger_agent.memory import sqlite_store
    from jaeger_agent.cognition.sqlite_runs import SqliteRunStore,SqliteEffectLedger
    from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
    from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
    from jaeger_ai import main
    from jaeger_ai.core.runtime.work_ledger import work_ledger,active_ledger,complete_task
    monkeypatch.setitem(main._pipeline,'layout',SimpleNamespace(root=tmp_path,run_dir=tmp_path/'run'))
    memory=SimpleNamespace(memory_dir=tmp_path/'native-memory')
    sqlite_store.bind(memory)
    runs=SqliteRunStore()
    commitment=SqliteCommitmentStore().create('Synthetic local controller task')
    native=runs.create(commitment.id)
    runs.transition(native.id,'active')
    calls=[]
    effects=[]
    def step(prompt,**kw):
        sqlite_store.bind(memory)
        calls.append(kw['request_id'])
        row=env.app.store.get_request(kw['request_id'])
        if kw['request_id']=='controller':
            if active_ledger() is None:
                work_ledger(action='create',task_name='Checked report',total_items=1,
                    remaining_ids=['report'],verify={'kind':'paths_exist','paths':[str(env.workspace/'report.txt')]})
            env.app.store.bind_native('controller',native_run_id=native.id,
                                     native_session=OWNER_RUN_SESSION_PREFIX+'s')
            SqliteEffectLedger().once('first-effect','synthetic',lambda:effects.append('first') or 'done',run_id=native.id)
            runs.checkpoint(native.id,{'messages':[{'role':'assistant','content':'First local effect checked'}]})
            return {'text':'First local effect checked','halt_reason':'hit max_iterations=8 without a final answer'}
        assert row['native_run_id']==native.id
        SqliteEffectLedger().once('final-effect','synthetic',lambda:effects.append('final') or 'done',run_id=native.id)
        path=env.workspace/'report.txt'
        path.write_text('Checked final report')
        work_ledger(action='update',completed_ids=['report'],remaining_ids=[],remaining_count=0)
        completed=complete_task(summary='Checked final report',evidence=str(path))
        assert completed['ok']
        return {'text':'Checked final report'}
    env.app._owner_react_turn=step
    admitted=env.app.store.admit_request('s',REQUEST,request_id='controller',requested={
        'workspace':str(env.workspace),'model':'frozen-model','provider':'frozen-provider',
        'caller':'human:operator','allowed_tools':['read_file','write_file'],'interaction_tier':'agent'})
    try:
        env.app._start_admitted_turn(admitted,'s',REQUEST)
        await env.app._running_tasks['controller']
        assert calls==['controller']*5
        assert env.app.task_owner.store.get_task('turn:controller').state==TaskState.PAUSED
        await drain(env.app.task_owner,5)
        assert calls==['controller']*5+['turn:controller:0']
        assert effects==['first','final']
        task=env.app.task_owner.store.get_task('turn:controller')
        assert task.state==TaskState.COMPLETED_VERIFIED and task.payload['delivered']
        assert len(env.app.task_owner.store.list_tasks())==1
        assert len(env.app.store.list_requests())==2
    finally:
        sqlite_store.close()

@pytest.mark.asyncio
async def test_cancel_during_foreground_settles_after_original_receipt(gateway):
    tid,_=seed(gateway,status=None)
    await gateway.task_owner.cancel(tid)
    assert gateway.task_owner.store.get_task(tid).state==TaskState.PAUSED
    gateway.store.complete_request('foreground',status='cancelled',result={'error':'cancelled'})
    await drain(gateway.task_owner)
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.CANCELLED and task.cancellation
    assert len(gateway.store.list_requests())==1

@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['foreground','promoted','completed_continuation'])
async def test_cancel_cannot_resolve_unknown_native_effect(gateway,phase):
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    tid,native=seed(gateway)
    if phase!='foreground':
        await gateway.task_owner.tick()
    if phase=='completed_continuation':
        task=gateway.task_owner.store.get_task(tid)
        sid='task:'+tid
        gateway.task_owner._execution_session(task)
        _admit_continuation(gateway,task)
        gateway.store.bind_native(tid+':0',native_run_id=native,native_session='owner:'+sid)
        gateway.store.complete_request(tid+':0',status='completed',result={'halt_reason':'yielded','output':'More progress'})
    def unknown():
        raise RuntimeError('Uncertain synthetic effect')
    with pytest.raises(RuntimeError):
        SqliteEffectLedger().once('cancel-pending','synthetic',unknown,run_id=native)
    await gateway.task_owner.cancel(tid)
    await drain(gateway.task_owner)
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.PAUSED and task.cancellation
    assert not task.payload.get('delivered')

@pytest.mark.asyncio
@pytest.mark.parametrize('field',['session_id','caller','allowed_tools','model','options','display_text',
                                 'input_text','native_run_id','native_session','missing_native'])
@pytest.mark.parametrize('status',['completed','cancelled','failed'])
async def test_foreign_terminal_receipt_never_settles_or_changes_history(gateway,field,status):
    import hashlib,json
    from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
    tid,native=seed(gateway)
    await gateway.task_owner.tick()
    task=gateway.task_owner.store.get_task(tid)
    row=_admit_continuation(gateway,task)
    rid=row['request_id']
    gateway.store.bind_native(rid,native_run_id=native,native_session=OWNER_RUN_SESSION_PREFIX+'task:'+tid)
    path=gateway.store.path.parent/'unrelated.txt';path.write_text('Unrelated artifact')
    gateway.store.complete_request(rid,status=status,result={'output':'Foreign result',
        'task_completion':{'ok':True,'verification_receipts':[{'kind':'file_sha256','path':str(path),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}})
    gateway.store.ensure_session('foreign')
    with gateway.store._immediate() as conn:
        if field in {'session_id','input_text','native_run_id','native_session','missing_native'}:
            column='native_run_id' if field=='missing_native' else field
            value=None if field=='missing_native' else 'foreign'
            conn.execute(f'UPDATE client_requests SET {column}=? WHERE request_id=?',(value,rid))
        else:
            execution=gateway.store.get_request(rid)['execution']
            execution[field]={'task_id':'foreign'} if field=='options' else [] if field=='allowed_tools' else 'foreign'
            conn.execute('UPDATE client_requests SET execution_json=? WHERE request_id=?',(json.dumps(execution),rid))
    before=gateway.task_owner.store.get_task(tid)
    gateway._start_admitted_turn=lambda *a:pytest.fail('Foreign receipt must not execute')
    await gateway.task_owner._execute(tid)
    after=gateway.task_owner.store.get_task(tid)
    assert after.state==TaskState.PAUSED and not after.payload.get('delivered')
    assert after.result==before.result and after.run_history==before.run_history
    assert after.payload['native_run_id']==native
    assert not after.payload.get('verification')

@pytest.mark.asyncio
async def test_admission_race_cannot_bind_or_signal_foreign_request(gateway,monkeypatch):
    tid,native=seed(gateway)
    await gateway.task_owner.tick()
    original=gateway.store.admit_request
    gateway.store.ensure_session('foreign')
    def raced(sid,prompt,**kwargs):
        foreign_kwargs={k:v for k,v in kwargs.items() if k!='admission_guard'}
        original('foreign',prompt,**foreign_kwargs)
        return original(sid,prompt,**kwargs)
    monkeypatch.setattr(gateway.store,'admit_request',raced)
    gateway._start_admitted_turn=lambda *a:pytest.fail('Foreign admission must not start')
    await gateway.task_owner._execute(tid)
    row=gateway.store.get_request(tid+':0')
    assert row['session_id']=='foreign' and row['native_run_id'] is None
    held=gateway.task_owner.store.get_task(tid)
    assert held.state==TaskState.PAUSED and not held.payload.get('delivered')
    assert [r.run_id for r in held.run_history]==['foreground']
    assert not gateway._cancellations.is_cancelled(tid+':0')
    # Reconciliation observes the collision without retry spin or foreign work.
    await gateway.task_owner._execute(tid)
    assert gateway.store.get_request(tid+':0')==row
    assert gateway.task_owner.store.get_task(tid).state==TaskState.PAUSED
    from dev.tests.jaeger_ai.core.test_foreground_transfer_recovery import owned_pending_child
    child=owned_pending_child(gateway)
    await gateway.task_owner.cancel(tid)
    assert gateway.store.get_handoff(child['id'])['status']=='cancelled'
    assert not gateway._cancellations.is_cancelled(tid+':0')
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.PAUSED and task.cancellation and not task.payload.get('delivered')
    assert [r.run_id for r in task.run_history]==['foreground']

@pytest.mark.asyncio
async def test_background_task_rejects_foreign_session_receipt(gateway):
    tid=gateway.task_owner.submit('Complete report',context={'source':'client','session_id':'parent',
        'execution':{'workspace':str(gateway.store.path.parent)}})['task_id']
    gateway.store.ensure_session('foreign')
    gateway.store.admit_request('foreign','Unrelated',request_id=tid+':0')
    gateway.store.complete_request(tid+':0',status='cancelled',result={'output':'Foreign result'})
    await gateway.task_owner._execute(tid)
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.PAUSED and task.result is None and not task.run_history
    assert not task.payload.get('delivered')

@pytest.mark.asyncio
@pytest.mark.parametrize('promoted',[False,True])
async def test_pending_cancellation_ticks_do_not_repeat_task_fanout(gateway,promoted):
    from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger
    from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
    tid,native=seed(gateway)
    if promoted:
        await gateway.task_owner.tick()
        task=gateway.task_owner.store.get_task(tid)
        _admit_continuation(gateway,task)
        gateway.store.bind_native(tid+':0',native_run_id=native,native_session=OWNER_RUN_SESSION_PREFIX+'task:'+tid)
        gateway.store.complete_request(tid+':0',status='completed',result={'halt_reason':'yielded','output':'Retained'})
    def uncertain():
        raise RuntimeError('pending local effect')
    with pytest.raises(RuntimeError):
        SqliteEffectLedger().once('pending-cancel-noop','synthetic',uncertain,run_id=native)
    await gateway.task_owner.cancel(tid)
    await drain(gateway.task_owner,1) # first reconciliation can retain new progress
    def updates():
        return [e for e in gateway.event_bus.get_replay_events('parent',since_event_id=0)
                if e.event=='task.updated' and e.data['task']['task_id']==tid]
    before=len(updates())
    await drain(gateway.task_owner,4)
    assert len(updates())==before
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.PAUSED and task.cancellation and not task.payload.get('delivered')

@pytest.mark.asyncio
async def test_terminal_contract_survives_changed_owner_feedback(gateway):
    import hashlib
    from jaeger_ai.core.gateway.server import OWNER_RUN_SESSION_PREFIX
    tid,native=seed(gateway)
    await gateway.task_owner.tick()
    task=gateway.task_owner.store.get_task(tid)
    _admit_continuation(gateway,task)
    gateway.store.bind_native(tid+':0',native_run_id=native,native_session=OWNER_RUN_SESSION_PREFIX+'task:'+tid)
    path=gateway.store.path.parent/'valid.txt';path.write_text('Valid result')
    gateway.store.complete_request(tid+':0',status='completed',result={'output':'Valid result',
        'task_completion':{'ok':True,'verification_receipts':[{'kind':'file_sha256','path':str(path),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}})
    gateway.task_owner.store.update_task(tid,lambda t:setattr(t,'error','Later owner observation'))
    await gateway.task_owner._execute(tid)
    task=gateway.task_owner.store.get_task(tid)
    assert task.state==TaskState.COMPLETED_VERIFIED and task.result=='Valid result'
    assert task.payload['delivered']

@pytest.mark.asyncio
async def test_running_receipt_without_native_binding_is_not_restarted(gateway):
    tid,_=seed(gateway)
    await gateway.task_owner.tick()
    task=gateway.task_owner.store.get_task(tid)
    _admit_continuation(gateway,task)
    gateway.store.mark_request_status(tid+':0','running')
    gateway._start_admitted_turn=lambda *a:pytest.fail('Running unbound receipt is not an unstarted admission')
    await gateway.task_owner._execute(tid)
    assert gateway.store.get_request(tid+':0')['native_run_id'] is None
    assert gateway.task_owner.store.get_task(tid).state==TaskState.PAUSED
