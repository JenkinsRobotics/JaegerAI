"""Owned local exchange fixtures; no model, external agent, live store or credentials."""
import json
import pytest
from dev.tests.jaeger_ai.core.test_sessions_contract import gw
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.agent_presentation import project, validate_patch
from jaeger_ai.core.gateway.caller_auth import client_headers, required_scope, prefixed_route_allowed


def parent(store, status='completed', hid='owned-thread'):
    return store.save_handoff({'id': hid, 'request_id': 'owned-request-'+hid, 'from_agent_id': 'native:everyday', 'to_agent_id': 'native:builder', 'session_id': 'owned-home', 'task': 'owned earlier work', 'status': status, 'require_approval': False, 'metadata': {'allowed_tools': ['read_file']}, 'result': {'summary': 'owned result'}})


@pytest.mark.asyncio
async def test_followup_is_durable_correlated_idempotent_and_waits_for_approval(gw):
    app, client = gw
    app.store.ensure_session('owned-home', metadata={'agent_id': 'native:everyday', 'home': True})
    app.store.append_message('owned-home', 'user', 'retained original context')
    original = parent(app.store)
    registry_before = [a.to_dict() for a in app._registry().list_agents()]
    response = await client.post('/v1/handoffs/owned-thread/reply', json={'task': 'owned follow-up', 'request_id': 'owned-followup'})
    data = await response.json()
    assert response.status == 202, data
    assert data['status'] == 'pending_approval' and data['require_approval']
    assert data['session_id'] == 'owned-home' and data['from_agent_id'] == original['from_agent_id'] and data['to_agent_id'] == original['to_agent_id']
    assert data['metadata']['thread_handoff_id'] == original['id'] and data['metadata']['reply_to_handoff_id'] == original['id']
    assert data['metadata']['allowed_tools'] == ['read_file']
    assert 'owned result' in data['metadata']['permitted_context']
    assert app.store.list_pending_approvals() and not app._running_tasks
    repeat = await (await client.post('/v1/handoffs/owned-thread/reply', json={'task': 'owned follow-up', 'request_id': 'owned-followup'})).json()
    assert repeat['id'] == data['id'] and len(app.store.list_handoffs()) == 2
    assert (await client.post('/v1/handoffs/owned-thread/reply', json={'task': 'different', 'request_id': 'owned-followup'})).status == 409
    reopened = GatewaySessionStore(app.store.path)
    assert reopened.get_handoff(data['id'])['metadata']['thread_handoff_id'] == original['id']
    assert [a.to_dict() for a in app._registry().list_agents()] == registry_before
    assert app.store.get_handoff(original['id']) == original
    assert app.store.list_messages('owned-home')['messages'][0]['content'] == 'retained original context'


@pytest.mark.asyncio
async def test_unknown_active_bad_fields_and_unprivileged_reply_fail_closed(gw):
    app, client = gw
    app.store.ensure_session('owned-home')
    unknown = parent(app.store, 'execution_unknown', 'owned-unknown')
    running = parent(app.store, 'running', 'owned-running')
    for row in [unknown, running]:
        assert (await client.post('/v1/handoffs/'+row['id']+'/reply', json={'task': 'do not execute', 'request_id': 'new-'+row['id']})).status == 409
        assert app.store.get_handoff(row['id']) == row
    parent(app.store)
    assert (await client.post('/v1/handoffs/owned-thread/reply', json={'task': 'x', 'request_id': 'x', 'require_approval': False})).status == 400
    assert (await client.post('/v1/handoffs/owned-thread/reply', headers=client_headers('mcp'), json={'task': 'x', 'request_id': 'x'})).status == 403
    assert required_scope('POST', '/v1/handoffs/{id}/reply') == 'admin'
    assert not prefixed_route_allowed('POST', '/v1/handoffs/{id}/reply')
    assert not app.store.list_pending_approvals() and not app._running_tasks


def test_icon_is_independent_durable_metadata_and_posts_keep_status_once(tmp_path):
    store = GatewaySessionStore(tmp_path/'owned.sqlite3'); store.ensure_session('owned-home')
    row = {'id':'native:owned','name':'Original','role':'specialist','kind':'jaeger_native','allowed_tools':['read_file']}
    store.patch_agent_presentation(row['id'], {'icon_preset':'robot-shield','display_name':'Alias','pinned':True})
    store.set_primary_agent(row['id'], 'native:jaeger')
    store.patch_agent_presentation(row['id'], {'pinned':False,'archived':True})
    reopened = GatewaySessionStore(store.path)
    projected = project(row, reopened.agent_presentation(), primary_id=reopened.primary_agent_id(), writable=True)
    assert projected['icon_preset'] == 'robot-shield' and projected['primary'] and projected['archived'] and not projected['pinned']
    assert projected['allowed_tools'] == ['read_file'] and projected['role'] == 'specialist'
    with pytest.raises(ValueError): validate_patch({'icon_preset':'remote-file'})
    kwargs = dict(kind='handoff_result', sender_agent_id=row['id'], links={'handoff_id':'owned-h','thread_handoff_id':'owned-thread','reply_to_handoff_id':'owned-parent'}, meta={'status':'completed'})
    mid=store.append_handoff_post_once('owned-home','assistant','owned result',**kwargs)
    assert reopened.append_handoff_post_once('owned-home','assistant','owned result',**kwargs)==mid
    message=reopened.list_messages('owned-home')['messages'][0]
    assert message['status']=='completed' and message['links']['thread_handoff_id']=='owned-thread'
    assert len(reopened.list_messages('owned-home')['messages']) == 1
    with pytest.raises(ValueError):
        reopened.append_handoff_post_once('owned-home','assistant','conflicting result',**kwargs)
    store.deliver_task_result('owned-task','owned-home','done','completed',sender_agent_id=row['id'])
    assert reopened.list_messages('owned-home')['messages'][0]['status']=='completed'


@pytest.mark.asyncio
async def test_approved_followup_executes_correlated_child_and_posts_result(gw, monkeypatch):
    import asyncio
    app, client = gw
    app.store.ensure_session('owned-home', metadata={'agent_id': 'native:everyday'})
    parent(app.store)
    before = [a.to_dict() for a in app._registry().list_agents()]
    seen = []

    # Script only the local model transport. Real admission, delegate runtime,
    # approval, worker receipt and terminal exchange producers remain in use.
    async def local_model(session_id, turn_id, text, *, request_id=None, execution=None):
        seen.append((session_id, text, execution))
        app._persist_terminal(request_id, session_id, 'completed', {'output': 'isolated correlated answer', 'backend': 'fixture'}, assistant_text='isolated correlated answer', record_entity_event=False)
    monkeypatch.setattr(app, '_execute_turn_inner', local_model)
    response = await client.post('/v1/handoffs/owned-thread/reply', json={'task': 'return local answer', 'request_id': 'successful-followup'})
    assert response.status == 202
    child = await response.json()
    assert not seen and child['status'] == 'pending_approval'
    approval = next(a for a in app.store.list_pending_approvals() if a['metadata'].get('handoff_id') == child['id'])
    assert (await client.post('/v1/approvals/'+approval['approval_id'], headers=client_headers('ares'), json={'decision': 'once'})).status == 403
    assert (await client.post('/v1/approvals/'+approval['approval_id'], json={'decision': 'once'})).status == 200
    for _ in range(300):
        if app.store.get_handoff(child['id'])['status'] in {'completed', 'failed'}: break
        await asyncio.sleep(.01)
    result = app.store.get_handoff(child['id'])
    assert result['status'] == 'completed', result
    assert result['result']['summary'] == 'isolated correlated answer'
    assert len(seen) == 1 and seen[0][2]['allowed_tools'] == ['read_file']
    exchange = await (await client.get('/v1/handoffs/'+child['id']+'/messages')).json()
    assert exchange['reply_to_handoff_id'] == 'owned-thread' and exchange['thread_handoff_id'] == 'owned-thread'
    assert exchange['messages'][-1]['content'] == 'isolated correlated answer'
    posts = app.store.list_messages('owned-home')['messages']
    assert any(m['kind'] == 'handoff_result' and m['links']['handoff_id'] == child['id'] for m in posts)
    assert [a.to_dict() for a in app._registry().list_agents()] == before
    repeat = await client.post('/v1/handoffs/owned-thread/reply', json={'task': 'return local answer', 'request_id': 'successful-followup'})
    assert repeat.status == 200 and (await repeat.json())['id'] == child['id']
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_standalone_followup_pending_approval_is_session_scoped_and_recovers_old_rows(gw):
    app, client = gw
    app.store.ensure_session('owned-home')
    parent(app.store)
    child=await (await client.post('/v1/handoffs/owned-thread/reply',json={'task':'explicit bounded followup','request_id':'visible-followup'})).json()
    approval=app.store.get_approval(child['approval_id'])
    assert approval['session_id']=='owned-home'
    data=await (await client.get('/v1/approvals?session_id=owned-home')).json()
    assert data['approvals'][0]['approval_id']==approval['approval_id']
    assert data['approvals'][0]['task']=='explicit bounded followup'
    # Backward recovery is read-only, from durable handoff correlation.
    with app.store._get_conn() as conn:
        conn.execute('UPDATE approvals SET session_id=NULL WHERE approval_id=?',(approval['approval_id'],))
    data=await (await client.get('/v1/approvals?session_id=owned-home')).json()
    assert data['approvals'][0]['session_id']=='owned-home'
    assert app.store.get_approval(approval['approval_id'])['session_id'] is None
    assert (await (await client.get('/v1/approvals?session_id=foreign-home')).json())['approvals']==[]
    assert (await client.get('/v1/approvals?session_id=owned-home',headers=client_headers('ares'))).status==403
    assert app.store.get_handoff(child['id'])['status']=='pending_approval'
    assert not app._running_tasks
