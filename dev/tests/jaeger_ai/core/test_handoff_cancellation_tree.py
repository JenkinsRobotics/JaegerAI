"""Owned, isolated cancellation relationships; no model/provider dispatch."""
import pytest

from jaeger_ai.contract.handoffs import child_request_id
from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
from jaeger_ai.core.gateway.handoff_cancellation import unconfirmed_ids
from jaeger_ai.core.runtime.cancellation import bind_agent

pytest_plugins = ('dev.tests.jaeger_ai.core.test_sessions_contract',)


def root(app, name='root', agent='native:everyday'):
    sid=app._ensure_agent_home(agent)[0]
    row=app.store.admit_request(sid,'owned fixture only',request_id='owned-'+name,requested={'caller':'owner:webui'})
    return row


async def pending(app,http,parent,nonce,target='native:builder',**options):
    response=await http.post('/v1/agents/'+target+'/handoff',json={'task':'owned fixture','request_id':'owned-'+nonce,'parent_request_id':parent['request_id'],'session_id':parent['session_id'],'require_approval':True,**options})
    assert response.status==200 or response.status==202,await response.text()
    return await response.json()


def child(app,record,status='execution_unknown',wrong=False):
    sid=specialist_session(record['to_agent_id'],record['request_id'])
    app.store.ensure_session(sid,metadata={'handoff_id':'foreign' if wrong else record['id'],'agent_id':record['to_agent_id'],'parent_session_id':record['session_id']})
    rid=child_request_id(record['request_id'])
    row=app.store.admit_request(sid,'owned child fixture',request_id=rid,requested={'caller':'owner:webui','is_subordinate':True})
    if status in {'execution_unknown','completed','failed','cancelled'}:app.store.complete_request(rid,status=status,result={'error':'uncertain fixture effect'} if status=='execution_unknown' else {'output':'owned retained outcome'})
    return app.store.get_request(row['request_id'])


@pytest.mark.asyncio
async def test_pending_owned_only_sticky_cancel_denies_approval_and_repeated_stop(gw):
    app,http=gw;parent=root(app);row=await pending(app,http,parent,'pending')
    assert row['from_agent_id']=='native:everyday'
    assert row['metadata']['parent_binding']['request_id']==parent['request_id']
    stale=dict(row)
    independent=app.store.save_handoff({**row,'id':'owned-independent','request_id':'owned-independent-request','parent_run_id':None,'approval_id':None,'metadata':{'caller_actor':'owner:webui'},'status':'admitted'})
    historical=app.store.save_handoff({**row,'id':'owned-historical','request_id':'owned-historical-request','approval_id':None,'metadata':{'caller_actor':'owner:webui'},'status':'admitted'})
    for _ in range(2):
        response=await http.post('/v1/sessions/'+parent['session_id']+'/cancel',json={'request_id':parent['request_id']})
        assert response.status==200
        data=await response.json()
        own=next(v for v in data['owned_handoff_cancellations'] if v['handoff_id']==row['id'])
        assert own['cancellation_confirmed'] and own['confirmation_scope']=='pre_admission'
        assert historical['id'] in data['unconfirmed_task_ids']
    saved=app.store.get_handoff(row['id']);assert saved['status']=='cancelled'
    approval=app.store.get_approval(row['approval_id']);assert approval['status']=='resolved' and approval['decision']=='cancelled'
    app.store.save_handoff({**stale,'status':'running'})
    assert app.store.get_handoff(row['id'])==saved
    assert app.store.get_handoff(independent['id'])==independent
    assert app.store.get_handoff(historical['id'])==historical
    assert app.store.get_request(child_request_id(row['request_id'])) is None
    assert (await http.post('/v1/agents/native:builder/handoff',json={'task':'must not run','request_id':'owned-after-stop','parent_request_id':parent['request_id'],'session_id':parent['session_id']})).status==409


@pytest.mark.asyncio
@pytest.mark.parametrize('first_status',['execution_unknown','completed','failed','cancelled'])
async def test_unknown_child_and_nested_descendant_signal_only_bound_scopes_and_keep_receipts(gw,first_status):
    app,http=gw;parent=root(app);row=await pending(app,http,parent,'active')
    app.store.save_handoff({**row,'status':'running'})
    first=child(app,row,status=first_status)
    # An uncertain child cannot initiate new work. Seed an already retained
    # grandchild relationship, as it may exist before an interruption.
    from jaeger_ai.core.gateway.handoff_ownership import parent_context
    context=parent_context(app,first['request_id'],first['session_id'],'owner:webui')
    grand=app.store.save_handoff({**row,'id':'owned-grand','request_id':'owned-grand-request','session_id':first['session_id'],'from_agent_id':'native:builder','to_agent_id':'native:everyday','parent_run_id':first['request_id'],'approval_id':None,'status':'running','metadata':{'caller_actor':'owner:webui','parent_binding':context['binding']}})
    second=child(app,grand)
    foreign=app.store.save_handoff({**row,'id':'owned-foreign','request_id':'owned-foreign-request','status':'running'})
    foreign_child=child(app,foreign,wrong=True)
    class Agent:
        def __init__(self):self.interrupts=0
        def interrupt(self):self.interrupts+=1
        def bind_cancel_signal(self,signal):self.signal=signal
    agents=[]
    for request in (first,second,foreign_child):
        agent=Agent();bind_agent(app._cancellations.register(request['request_id']),agent);agents.append(agent)
    before=[app.store.get_request(r['request_id']) for r in (first,second,foreign_child)]
    for _ in range(2):
        response=await http.post('/v1/sessions/'+parent['session_id']+'/cancel',json={'request_id':parent['request_id']})
        assert response.status==200
        data=await response.json()
        assert {second['request_id'],foreign['id']}<=set(data['unconfirmed_task_ids'])
        assert (first['request_id'] in data['unconfirmed_task_ids'])==(first_status=='execution_unknown')
    assert [a.interrupts for a in agents]==[1,1,0]
    assert before==[app.store.get_request(r['request_id']) for r in (first,second,foreign_child)]
    saved=app.store.get_handoff(row['id']);assert saved['metadata']['cancel_requested']
    app.store.save_handoff({**row,'status':'running'})
    assert app.store.get_handoff(row['id'])['metadata']['cancel_requested']
    assert app.store.get_handoff(foreign['id'])==foreign
    assert unconfirmed_ids([{'handoff_id':'h','outcome':'terminal','descendants':[{'handoff_id':'g','outcome':'unknown','child_request_id':'r'}]}])==['r']


@pytest.mark.asyncio
async def test_nested_producer_uses_actual_identity_and_refuses_self_delegation(gw):
    app,http=gw;parent=root(app);row=await pending(app,http,parent,'nested-parent')
    first=child(app,row,status='admitted')
    nested=await pending(app,http,first,'nested-child',target='native:researcher')
    assert nested['from_agent_id']=='native:builder' and nested['parent_run_id']==first['request_id']
    response=await http.post('/v1/agents/native:builder/handoff',json={'task':'no self loop','request_id':'owned-self','parent_request_id':first['request_id'],'session_id':first['session_id']})
    assert response.status==409
    assert app.store.get_handoff_by_request('owned-self') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('receipt_status',['admitted','execution_unknown'])
@pytest.mark.parametrize('label',['cancelled','completed'])
async def test_bound_child_truth_overrides_stale_terminal_handoff_label(gw,receipt_status,label):
    app,http=gw;parent=root(app);row=await pending(app,http,parent,'stale-label')
    app.store.save_handoff({**row,'status':label,'metadata':{**row['metadata'],'cancelled_before_admission':True}})
    admitted=child(app,row,status=receipt_status)
    before=app.store.get_request(admitted['request_id'])
    response=await http.post('/v1/sessions/'+parent['session_id']+'/cancel',json={'request_id':parent['request_id']})
    assert response.status==200
    data=await response.json();value=next(r for r in data['owned_handoff_cancellations'] if r['handoff_id']==row['id'])
    assert value['outcome']==('unknown' if receipt_status=='execution_unknown' else 'requested')
    assert value['cancellation_confirmed'] is False and admitted['request_id'] in data['unconfirmed_task_ids']
    assert app._cancellations.is_cancelled(admitted['request_id'])
    if receipt_status=='execution_unknown':assert app.store.get_request(admitted['request_id'])==before
    else:assert app.store.get_request(admitted['request_id'])['status']=='cancelling'
    assert len(app.store.list_requests())==2


@pytest.mark.asyncio
async def test_explicit_leaf_command_owner_scope_original_lookup_unknown_no_replay(gw,monkeypatch):
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.gateway.handoff_controls import command_key
    app,http=gw;parent=root(app);row=await pending(app,http,parent,'leaf')
    before=app.store.get_request(parent['request_id'])
    path='/v1/handoffs/'+row['id']+'/stop-commands'
    body={'operation_id':'owned-stop-command','request_id':row['request_id']}
    assert (await http.post(path,json=body,headers=client_headers('jaegerd'))).status==403
    assert (await http.get('/v1/handoff-controls',headers=client_headers('jaegerd'))).status==403
    assert (await http.get('/v1/handoff-controls',headers=client_headers('a2a'))).status==403
    assert (await http.post(path,json={**body,'request_id':'foreign'})).status==409
    first=await (await http.post(path,json=body)).json()
    assert first['outcome']=='accepted' and first['current']['cancellation_confirmed']
    assert first['unconfirmed_task_ids']==[]
    monkeypatch.setattr('jaeger_ai.core.gateway.handoff_stop_controls.cancel_one',lambda *a,**k:pytest.fail('Retained command cannot repeat Stop executor'))
    assert await (await http.get(path+'/'+body['operation_id'])).json()==first
    assert await (await http.post(path,json=body)).json()==first
    assert app.store.get_request(parent['request_id'])==before
    assert (await http.get(path+'/'+body['operation_id'],headers=client_headers('jaegerd'))).status==403
    listed=await (await http.get('/v1/handoff-controls')).json()
    assert listed['limit']==100 and listed['handoffs'][0]['handoff_id']==row['id']
    # A crash after reservation but before intent is unknown; never rerun.
    unknown={**body,'operation_id':'owned-unresolved-stop'}
    app.store.reserve_control_operation(command_key('handoff_stop',row['id'],unknown['operation_id'],'owner:webui'),{'scope':'handoff_stop','resource':row['id'],'actor':'owner:webui','body':unknown})
    assert (await (await http.post(path,json=unknown)).json())['outcome']=='unknown'
    assert (await (await http.get(path+'/'+unknown['operation_id'])).json())['outcome']=='unknown'


@pytest.mark.asyncio
async def test_model_discovery_yield_cannot_admit_child_after_stop(gw,monkeypatch):
    import asyncio
    app,http=gw;parent=root(app)
    monkeypatch.setattr(app,'_session_model_choice',lambda _: {'model':'owned-model','provider':'ollama'})
    row=await pending(app,http,parent,'discovery',model='@ollama:owned-model')
    app.store.save_handoff({**row,'status':'running'})
    started=asyncio.Event();release=asyncio.Event()
    async def discovery(*args):started.set();await release.wait();
    monkeypatch.setattr(app,'_turn_model_revision',discovery)
    monkeypatch.setattr(app,'_start_admitted_turn',lambda *a:pytest.fail('Cancelled child must not execute'))
    sid=specialist_session(row['to_agent_id'],row['request_id'])
    task=asyncio.create_task(app._specialist_chat(sid,'fixture',request_id=row['request_id'],agent_id=row['to_agent_id'],handoff_id=row['id'],parent_session_id=parent['session_id']))
    await asyncio.wait_for(started.wait(),2)
    response=await http.post('/v1/sessions/'+parent['session_id']+'/cancel',json={'request_id':parent['request_id']})
    assert response.status==200
    release.set()
    with pytest.raises(ValueError,match='cancelled before child admission'):await task
    assert app.store.get_request(child_request_id(row['request_id'])) is None
