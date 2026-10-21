"""Owner command/option fixtures, no providers or model execution."""
import asyncio
import pytest
from dev.tests.jaeger_ai.core.test_sessions_contract import gw
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.handoff_controls import command_key


@pytest.mark.asyncio
async def test_owner_model_option_receipts_rejections_lookup_and_no_policy_mutation(gw,monkeypatch):
    app,http=gw
    origin='native:everyday';target='native:builder';home=app._ensure_agent_home(origin)[0]
    before=[a.to_dict() for a in app._registry().list_agents()]
    monkeypatch.setattr(app,'_session_model_choice',lambda value:{'model':'fixture-model','provider':'ollama'} if value=='@ollama:fixture-model' else None)
    body={'task':'owned fixture only','request_id':'owned-model-handoff','from_agent_id':origin,'session_id':home,'require_approval':True,'model':'@ollama:fixture-model','background':True}
    path=f'/v1/agents/{target}/handoff-commands'
    result=await (await http.post(path,json=body)).json()
    assert result['outcome']=='saved'
    row=result['handoff'];assert '@ollama:fixture-model' in app.store.list_pending_approvals()[0]['prompt']
    assert row['status']=='pending_approval' and row['metadata']['model_choice']=={'model':'fixture-model','provider':'ollama'}
    assert await (await http.post(path,json=body)).json()==result
    assert (await http.post(path,json={**body,'task':'different objective'})).status==409
    assert (await http.post(path,json=body,headers=client_headers('jaegerd'))).status==403
    assert (await http.get(path+'/'+body['request_id'],headers=client_headers('jaegerd'))).status==404
    assert (await http.get(path+'/'+body['request_id'],headers=client_headers('a2a'))).status==403
    assert await (await http.get(path+'/'+body['request_id'])).json()==result
    # Alternate legacy POST cannot repeat a retained owner command.
    assert (await http.post(f'/v1/agents/{target}/handoff',json=body)).status==409
    bad={**body,'request_id':'owned-unavailable-model','model':'@ollama:missing'}
    rejected=await (await http.post(path,json=bad)).json();assert rejected['outcome']=='rejected'
    assert app.store.get_handoff_by_request(bad['request_id']) is None
    monkeypatch.setattr(app,'_session_model_choice',lambda value:{'model':'now-present','provider':'ollama'})
    assert await (await http.post(path,json=bad)).json()==rejected # Original rejection wins after catalog change.
    assert app.store.get_handoff_by_request(bad['request_id']) is None
    assert [a.to_dict() for a in app._registry().list_agents()]==before
    assert not app._running_tasks and len(app.store.list_pending_approvals())==1
    assert app.store.get_session(home)['metadata'].get('model') is None
    # A retained reservation without admission stays unknown and is not replayed.
    unknown={**body,'request_id':'owned-unknown-command'}
    app.store.reserve_control_operation(command_key('handoff_request',target,unknown['request_id'],'owner:webui'),{'scope':'handoff_request','resource':target,'actor':'owner:webui','body':unknown})
    assert (await (await http.post(path,json=unknown)).json())['outcome']=='unknown'
    assert app.store.get_handoff_by_request(unknown['request_id']) is None


@pytest.mark.asyncio
async def test_concurrent_same_model_handoff_has_one_admission_and_child_snapshot_keeps_caller(gw,monkeypatch):
    app,http=gw;origin='native:everyday';target='native:builder';sid=app._ensure_agent_home(origin)[0]
    def choice(value):return {'model':'fixture-model','provider':'ollama'}
    monkeypatch.setattr(app,'_session_model_choice',choice)
    body={'task':'only owned fixture','request_id':'owned-concurrent-handoff','from_agent_id':origin,'session_id':sid,'require_approval':True,'model':'@ollama:fixture-model','background':True}
    path=f'/v1/agents/{target}/handoff-commands'
    responses=await asyncio.gather(http.post(path,json=body),http.post(path,json=body))
    values=[await r.json() for r in responses]
    assert all(v['outcome'] in {'saved','unknown'} for v in values)
    rows=[r for r in app.store.list_handoffs() if r['request_id']==body['request_id']]
    assert len(rows)==1 and len(app.store.list_pending_approvals())==1
    row=rows[0]
    monkeypatch.setattr('jaeger_ai.core.runtime.truth.provider_model_inventory',lambda:{'providers':[{'id':'ollama','reachable':True,'models':[{'id':'fixture-model','available':True}]}]})
    seen=[]
    def finish(admitted,session,text):
        seen.append(admitted)
        app.store.complete_request(admitted['request_id'],status='completed',result={'output':'fixture callback only','backend':'fixture'})
    monkeypatch.setattr(app,'_start_admitted_turn',finish)
    # This boundary fixture deliberately supplies the owner-approved child call,
    # not a real model/tool run. It verifies immutable routing/caller/tool ceiling.
    await app._specialist_chat('specialist:'+target+':owned-child','fixture',request_id='owned-child',allowed_tools=['read_file'],agent_id=target,handoff_id=row['id'])
    execution=seen[0]['execution']
    assert execution['model']=='fixture-model' and execution['provider']=='ollama'
    assert execution['caller']=='owner:webui' and execution['allowed_tools']==['read_file'] and execution['is_subordinate']
    assert app.store.get_session(sid)['metadata'].get('model') is None


@pytest.mark.asyncio
async def test_reply_owner_command_is_approval_bound_correlated_and_recovers_ack(gw,monkeypatch):
    app,http=gw
    sid=app._ensure_agent_home('native:everyday')[0]
    parent=app.store.save_handoff({'id':'owned-parent','request_id':'owned-parent-request','from_agent_id':'native:everyday','to_agent_id':'native:builder','session_id':sid,'task':'earlier owned fixture','status':'completed','require_approval':True,'metadata':{'allowed_tools':['read_file'],'requested_model':'@ollama:fixture-model'},'result':{'summary':'fixture earlier result'}})
    monkeypatch.setattr(app,'_session_model_choice',lambda value:{'model':'fixture-model','provider':'ollama'})
    body={'task':'owned next bounded work','request_id':'owned-next-command'};path='/v1/handoffs/owned-parent/reply-commands'
    response=await (await http.post(path,json=body)).json()
    assert response['outcome']=='saved' and response['handoff']['status']=='pending_approval'
    child=response['handoff'];assert child['metadata']['reply_to_handoff_id']==parent['id'] and child['metadata']['allowed_tools']==['read_file']
    assert child['metadata']['requested_model']=='@ollama:fixture-model' and child['session_id']==sid
    assert app.store.get_handoff(parent['id'])==parent
    assert await (await http.post(path,json=body)).json()==response
    assert await (await http.get(path+'/'+body['request_id'])).json()==response
    assert not app._running_tasks and len(app.store.list_pending_approvals())==1
    # Lost wrapper ACK has the same canonical admission proof, not a new child.
    oid=command_key('handoff_reply',parent['id'],body['request_id'],'owner:webui')
    with app.store._immediate() as conn:conn.execute("UPDATE control_operations SET receipt_json=NULL,status='execution_unknown' WHERE operation_id=?",(oid,))
    recovered=await (await http.get(path+'/'+body['request_id'])).json()
    assert recovered['outcome']=='saved' and recovered['handoff']['id']==child['id']
    assert len([r for r in app.store.list_handoffs() if r['request_id']==body['request_id']])==1
    assert (await http.post('/v1/handoffs/owned-parent/reply',json=body)).status==409


@pytest.mark.asyncio
async def test_owner_command_cannot_bypass_stop_or_live_owner_gate(gw,monkeypatch):
    from types import SimpleNamespace
    from jaeger_ai.core.gateway.global_stop import GlobalStop
    from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease
    app,http=gw
    body={'task':'no execution','request_id':'owned-blocked-command','session_id':'unused','from_agent_id':'native:everyday','require_approval':True,'model':None,'background':True}
    path='/v1/agents/native:builder/handoff-commands'
    monkeypatch.setattr(GlobalStop,'load',lambda:SimpleNamespace(engaged=lambda:True))
    assert (await http.post(path,json=body)).status==423
    monkeypatch.setattr(GlobalStop,'load',lambda:SimpleNamespace(engaged=lambda:False))
    monkeypatch.setattr(LifecycleLease,'load',lambda:SimpleNamespace(decide=lambda:SimpleNamespace(privileged_work_allowed=False,reason='owned fixture lease offline')))
    assert (await http.post(path,json=body)).status==423
    assert app.store.control_operation(command_key('handoff_request','native:builder',body['request_id'],'owner:webui')) is None
    assert app.store.get_handoff_by_request(body['request_id']) is None and not app._running_tasks


@pytest.mark.asyncio
async def test_disabled_target_rejects_before_admission_and_before_approved_child_start(gw,monkeypatch):
    from types import SimpleNamespace
    app,http=gw;registry=app._registry();target=registry.get_agent('native:builder');target.metadata={**target.metadata,'disabled':True}
    monkeypatch.setattr(app,'_registry',lambda:SimpleNamespace(get_agent=lambda aid:target if aid==target.id else registry.get_agent(aid)))
    sid=app._ensure_agent_home('native:everyday')[0]
    body={'task':'owned fixture','request_id':'owned-disabled-command','session_id':sid,'from_agent_id':'native:everyday','require_approval':True,'model':None,'background':True}
    response=await (await http.post('/v1/agents/native:builder/handoff-commands',json=body)).json()
    assert response['outcome']=='rejected' and 'disabled' in response['error']
    assert app.store.get_handoff_by_request(body['request_id']) is None and not app.store.list_pending_approvals()
    row=app.store.save_handoff({'id':'owned-disabled-approved','request_id':'owned-disabled-approved-request','from_agent_id':'native:everyday','to_agent_id':'native:builder','session_id':sid,'task':'owned fixture','status':'approved','require_approval':True,'metadata':{'caller_actor':'owner:webui'},'result':{}})
    called=[]
    monkeypatch.setattr(app,'_specialist_chat',lambda *args,**kwargs:called.append(args))
    await app._execute_handoff(row['id'])
    assert app.store.get_handoff(row['id'])['status']=='failed' and not called
    assert not app.store.list_requests() and not app._running_tasks


@pytest.mark.asyncio
async def test_unavailable_foreground_and_permission_override_never_admit(gw):
    app,http=gw
    base={'task':'must not run','request_id':'owned-denied-mode','require_approval':False}
    path='/v1/agents/native:builder/handoff'
    assert (await http.post(path,json={**base,'permission_mode':'bypass'})).status==403
    assert (await http.post(path,json={**base,'background':False})).status==400
    assert app.store.get_handoff_by_request(base['request_id']) is None
    assert not app.store.list_pending_approvals() and not app._running_tasks
