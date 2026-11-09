"""Qualified child native uncertainty must survive original Chat Stop."""
import json
import os
import pytest
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.cognition.sqlite_runs import SqliteRunStore, SqliteEffectLedger
from jaeger_ai.contract.handoffs import child_request_id
from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
from jaeger_ai.core.gateway.handoff_ownership import child_receipt
from dev.tests.jaeger_ai.core.test_foreground_transfer_recovery import gateway, seed


def accepted_child(app, parent_native, pending):
    actor=app.store.get_request('foreground')['execution']['caller']
    handoff=app.store.save_handoff({'id':'qualified-child','request_id':'qualified-child-request',
        'from_agent_id':'native:jaeger','to_agent_id':'native:builder','session_id':'parent',
        'parent_run_id':parent_native,'task':'Synthetic local child','status':'completed',
        'metadata':{'caller_actor':actor,'parent_binding':{'request_id':'foreground','session_id':'parent',
            'root_actor':actor,'child_actor':actor,'source_agent_id':'native:jaeger'}}})
    sid=specialist_session(handoff['to_agent_id'],handoff['request_id'])
    rid=child_request_id(handoff['request_id'])
    app.store.ensure_session(sid,metadata={'handoff_id':handoff['id'],'agent_id':handoff['to_agent_id'],'parent_session_id':'parent'})
    app.store.admit_request(sid,'Local child result',request_id=rid,requested={
        'caller':actor,'is_subordinate':True,'model':'synthetic-model','provider':'openai'})
    commitment=SqliteCommitmentStore().create('Accepted child',kind='delegation')
    runs=SqliteRunStore()
    run=runs.create(commitment.id,owner_pid=os.getpid(),relation='root')
    runs.transition(run.id,'active')
    runs.checkpoint(run.id,{'messages':[{'role':'assistant','content':'Retained local child'}]})
    app.store.bind_native(rid,native_run_id=run.id,native_session='owner:'+sid)
    if pending:
        def interrupted(): raise RuntimeError('Synthetic interruption after effect claim')
        with pytest.raises(RuntimeError):
            SqliteEffectLedger().once('child-effect','synthetic-local-write',interrupted,run_id=run.id)
    else:
        runs.transition(run.id,'completed')
    app.store.complete_request(rid,status='completed',result={'status':'completed','output':'Retained child result'})
    assert child_receipt(app,handoff)[3] is True
    return run.id


@pytest.mark.asyncio
@pytest.mark.parametrize('promoted',[False,True])
@pytest.mark.parametrize('pending',[False,True])
async def test_original_chat_stop_respects_qualified_child_native_outcome(gateway,promoted,pending):
    tid,native=seed(gateway)
    if promoted:
        await gateway.task_owner.tick()
        assert not gateway.task_owner.store.get_task(tid).provenance['turn_owned']
    child=accepted_child(gateway,native,pending)
    gateway._start_admitted_turn=lambda *a,**k:pytest.fail('Stop cannot replay execution')
    async def no_external(*a,**k):pytest.fail('No native MCP allowed')
    gateway._request_native_cancel=no_external
    class Request(dict):
        can_read_body=True
        match_info={'id':'parent'}
        async def json(self):return {'request_id':'foreground'}
    response=await gateway.handle_cancel_turn(Request())
    task=gateway.task_owner.store.get_task(tid)
    observation={'task_state':task.state.value,'delivered':task.payload.get('delivered'),
                 'response':json.loads(response.text),'pending_native_runs':[
                     effect.run_id for effect in SqliteEffectLedger().list(status='pending')]}
    (gateway.store.path.parent/'observation.json').write_text(json.dumps(observation,indent=2))
    if pending:
        assert child in observation['pending_native_runs']
        assert task.state.value=='paused', observation
        assert not task.payload.get('delivered')
        assert tid in observation['response']['unconfirmed_task_ids']
    else:
        assert task.state.value=='cancelled', observation


@pytest.mark.asyncio
@pytest.mark.parametrize('condition', ['active', 'missing', 'descendant_pending', 'ledger_unreadable', 'producer_running'])
async def test_terminal_slice_does_not_hide_native_uncertainty(gateway, monkeypatch, condition):
    from jaeger_ai.core.gateway.handoff_cancellation import status
    tid, native = seed(gateway)
    child = accepted_child(gateway, native, condition == 'active')
    runs = SqliteRunStore()
    if condition == 'active':
        # Even an empty effect ledger cannot prove an active producer finished.
        monkeypatch.setattr(SqliteEffectLedger, 'list', lambda *a, **k: [])
    elif condition == 'producer_running':
        import asyncio
        gateway._running_tasks[child_request_id('qualified-child-request')] = asyncio.get_running_loop().create_future()
    elif condition == 'missing':
        monkeypatch.setattr(SqliteRunStore, 'list', lambda *a, **k: [])
    elif condition == 'ledger_unreadable':
        def unreadable(*a, **k):
            raise OSError('Synthetic unavailable effect ledger')
        monkeypatch.setattr(SqliteEffectLedger, 'list', unreadable)
    else:
        commitment = SqliteCommitmentStore().create('Native descendant')
        descendant = runs.create(commitment.id, owner_pid=os.getpid(), parent_run_id=child,
                                 relation='delegation')
        runs.transition(descendant.id, 'active')
        runs.checkpoint(descendant.id, {'messages': []})
        def interrupted():
            raise RuntimeError('Synthetic descendant claim')
        with pytest.raises(RuntimeError):
            SqliteEffectLedger().once('descendant-effect', 'synthetic-local-write',
                                     interrupted, run_id=descendant.id)
        runs.transition(descendant.id, 'completed')
    value = status(gateway, gateway.store.get_handoff('qualified-child'))
    assert value['outcome'] == 'unknown'
    assert not value['cancellation_confirmed']


@pytest.mark.asyncio
@pytest.mark.parametrize('promoted', [False, True])
async def test_stop_remains_pending_after_owner_reconstruction(gateway, promoted):
    import asyncio
    from jaeger_ai.core.tasks.owner import GatewayTaskOwner
    tid, native = seed(gateway)
    if promoted:
        await gateway.task_owner.tick()
    child = accepted_child(gateway, native, True)
    gateway._start_admitted_turn = lambda *a, **k: pytest.fail('Stop must not replay')
    for owner in (gateway.task_owner, GatewayTaskOwner(gateway)):
        await owner.cancel(tid)
        for _ in range(3):
            await owner.tick()
            if owner._active:
                await asyncio.gather(*owner._active.values())
            task = owner.store.get_task(tid)
            assert task.state.value == 'paused'
            assert not task.payload.get('delivered')
            assert task.cancellation
            assert gateway._cancellations.is_cancelled(child_request_id('qualified-child-request'))
            assert len(gateway.store.list_requests()) == 2
            assert child in [effect.run_id for effect in SqliteEffectLedger().list(status='pending')]


@pytest.mark.asyncio
async def test_reconciled_child_allows_cancellation_without_replay(gateway):
    tid, native = seed(gateway)
    child = accepted_child(gateway, native, True)
    gateway._start_admitted_turn = lambda *a, **k: pytest.fail('No replay after Stop')
    await gateway.task_owner.cancel(tid)
    assert gateway.task_owner.store.get_task(tid).state.value == 'paused'
    # Only explicit synthetic reconciliation and terminal producer evidence
    # remove the veto. The cancellation handler must not resolve either itself.
    SqliteEffectLedger().resolve('child-effect', {'confirmed': 'synthetic'})
    await gateway.task_owner.cancel(tid)
    assert gateway.task_owner.store.get_task(tid).state.value == 'paused'
    SqliteRunStore().transition(child, 'completed')
    await gateway.task_owner.cancel(tid)
    task = gateway.task_owner.store.get_task(tid)
    assert task.state.value == 'cancelled'
    assert task.payload.get('delivered')
    await gateway.task_owner.tick()
    assert gateway.task_owner.store.get_task(tid).state.value == 'cancelled'
    assert len(gateway.store.list_requests()) == 2
