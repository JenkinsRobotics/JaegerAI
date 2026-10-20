"""Owned presentation fixtures; no real agent, execution, credential or model mutation."""
import pytest
from dev.tests.jaeger_ai.core.test_sessions_contract import gw
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

@pytest.mark.asyncio
async def test_sections_recoverable_delete_restore_preserve_identity_and_chat(gw):
    app,client=gw
    aid='native:everyday'
    home=await (await client.get('/v1/agents/'+aid+'/home')).json()
    app.store.append_message(home['session_id'],'user','owned retained context')
    before=[a.to_dict() for a in app._registry().list_agents()]
    response=await client.post('/v1/sections',json={'name':'Owned section'})
    assert response.status==201
    section=await response.json()
    assert (await client.patch('/v1/agents/'+aid,json={'section_id':section['id']})).status==200
    assert (await client.patch('/v1/agents/'+aid,json={'deleted':True})).status==200
    rows=(await (await client.get('/v1/agents')).json())['agents']
    row=next(a for a in rows if a['id']==aid)
    assert row['deleted'] and row['hidden'] and row['section_id']==section['id'] and not row['ui_actions']['primary']
    reopened=GatewaySessionStore(app.store.path)
    assert reopened.agent_presentation()[aid]['deleted']
    assert reopened.agent_sections()==[section]
    assert (await client.patch('/v1/agents/'+aid,json={'deleted':False,'archived':False})).status==200
    assert (await (await client.get('/v1/agents/'+aid+'/home')).json())['session_id']==home['session_id']
    assert app.store.list_messages(home['session_id'])['messages'][0]['content']=='owned retained context'
    assert [a.to_dict() for a in app._registry().list_agents()]==before

@pytest.mark.asyncio
async def test_existing_scopes_primary_protection_and_validation(gw):
    app,client=gw
    assert (await client.post('/v1/sections',headers=client_headers('ares'),json={'name':'not allowed'})).status==403
    assert (await client.patch('/v1/agents/native:everyday',headers=client_headers('ares'),json={'deleted':True})).status==403
    assert (await client.post('/v1/sections',json={'name':'\n'})).status==400
    assert (await client.post('/v1/sections',json={'name':'x','owner':'other'})).status==400
    assert (await client.patch('/v1/agents/native:everyday',json={'section_id':'section_'+'0'*32})).status==400
    assert (await client.patch('/v1/agents/native:gateway',json={'deleted':True})).status==409
    primary=app.store.primary_agent_id()
    assert (await client.patch('/v1/agents/'+primary,json={'deleted':True})).status==400
    assert app.store.primary_agent_id()==primary
    assert app.store.agent_sections()==[]
