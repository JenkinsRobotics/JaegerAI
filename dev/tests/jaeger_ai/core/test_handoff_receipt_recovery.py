"""Read existing current Gateway receipts; never dispatch or borrow a foreign child."""
import json

import pytest

from jaeger_ai.contract.handoffs import child_request_id, request_digest

pytest_plugins = ('dev.tests.jaeger_ai.core.test_sessions_contract',)


def setup(app, name, *, wrong=False):
    from jaeger_ai.core.agent_registry.specialist_runtime import specialist_session
    parent=app._ensure_agent_home('native:everyday')[0]
    record=app.store.save_handoff({'id':'owned-handoff-'+name,'request_id':'owned-request-'+name,'from_agent_id':'native:everyday','to_agent_id':'native:builder','session_id':parent,'task':'owned fixture only','status':'execution_unknown','require_approval':True,'metadata':{'caller_actor':'owner:webui'},'result':{}})
    sid=specialist_session(record['to_agent_id'],record['request_id'])
    app.store.ensure_session(sid,metadata={'handoff_id':'foreign' if wrong else record['id'],'agent_id':record['to_agent_id'],'parent_session_id':parent})
    rid=child_request_id(record['request_id'])
    app.store.admit_request(sid,'fixture only, no worker',request_id=rid,requested={'caller':'owner:webui','is_subordinate':True,'attachment_ids':[]})
    return record,sid,rid


@pytest.mark.asyncio
@pytest.mark.parametrize('status',['completed','failed','cancelled'])
async def test_unknown_handoff_recovers_actual_canonical_terminal_receipt_once(gw,monkeypatch,status):
    app,http=gw;record,sid,rid=setup(app,status)
    app.store.complete_request(rid,status=status,result={'output':'owned retained result','backend':'fixture'})
    monkeypatch.setattr(app,'_native_receipt',lambda *a:pytest.fail('Canonical child must not fall through to another receipt owner'))
    monkeypatch.setattr(app,'_start_admitted_turn',lambda *a:pytest.fail('Recovery never executes'))
    response=await (await http.get('/v1/handoffs/'+record['id'])).json()
    assert response['status']==status and response['result']['summary']=='owned retained result'
    assert response['result']['worker_session_id']==sid
    assert response['result']['metadata']['gateway_request_id']==rid
    assert response['result']['metadata']['result_scope']=='child_request_outcome'
    assert app.store.get_request(rid)['status']==status and len(app.store.list_requests())==1
    before=app.store.list_messages(record['session_id'])['messages']
    assert len([m for m in before if m['kind']=='handoff_result'])==1
    assert await (await http.get('/v1/handoffs/'+record['id'])).json()==response
    assert app.store.list_messages(record['session_id'])['messages']==before


@pytest.mark.asyncio
async def test_current_unknown_or_foreign_child_remains_unknown_without_fallback_or_content_leak(gw,monkeypatch):
    app,http=gw;record,sid,rid=setup(app,'unknown')
    app.store.complete_request(rid,status='execution_unknown',result={'error':'fixture unknown effect'})
    monkeypatch.setattr(app,'_native_receipt',lambda *a:pytest.fail('Current unknown is authoritative, never consult another owner'))
    before=app.store.get_request(rid)
    assert before['session_id']==sid
    response=await (await http.get('/v1/handoffs/'+record['id'])).json()
    assert response['status']=='execution_unknown' and app.store.get_request(rid)==before
    foreign,_,foreign_rid=setup(app,'foreign',wrong=True)
    app.store.complete_request(foreign_rid,status='completed',result={'output':'PRIVATE-FOREIGN-RESULT'})
    response=await (await http.get('/v1/handoffs/'+foreign['id'])).json()
    assert response['status']=='execution_unknown' and 'identity' in response['recovery_error']
    assert 'PRIVATE-FOREIGN-RESULT' not in json.dumps(response)
    assert app.store.get_handoff(foreign['id'])==foreign


def test_shared_digest_preserves_both_persisted_wire_id_lengths():
    import hashlib
    original=hashlib.sha256(b'handoff:owned-reference').hexdigest()
    assert request_digest('owned-reference')==original
    assert child_request_id('owned-reference')==original[:32]
