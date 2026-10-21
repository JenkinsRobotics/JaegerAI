"""Exact owner-local prompt snapshot; never copies runtime authority/history."""
import hashlib
import json

import pytest

from jaeger_ai.core.agent_registry import AgentRegistry
from jaeger_ai.core.gateway.caller_auth import client_headers

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_owner_template_export_revision_policy_no_history_or_authority(gw,tmp_path,monkeypatch):
    app,http=gw;registry=AgentRegistry(tmp_path/'owned-template-registry')
    monkeypatch.setattr(app,'_registry',lambda:registry)
    record=registry.create_agent('owned-export',role='specialist',metadata={'specialty':'local','operator_instructions':'Describe supplied evidence.','allowed_tools':['sensitive-owned-tool'],'account_secret':'never-export-this'})
    before=registry.get_agent(record.id).to_dict()
    app.store.ensure_session('owned-template-history',metadata={'agent_id':record.id})
    app.store.append_message('owned-template-history','user','private history never exported')
    path='/v1/agents/'+record.id+'/template-export?revision=0'
    response=await http.get(path);assert response.status==200
    receipt=await response.json();payload=json.loads(receipt['content'])
    assert hashlib.sha256(receipt['content'].encode()).hexdigest()==receipt['sha256']
    assert payload['source_bot']=={'agent_id':record.id,'configuration_revision':0}
    assert payload['version']==1 and payload['visibility']=='owner_local'
    assert payload['export_policy']=='prompt_only_no_grants'
    assert payload['tools_granted'] is False and payload['history_included'] is False and payload['credentials_included'] is False
    assert not any(value in receipt['content'] for value in ('sensitive-owned-tool','never-export-this','private history'))
    copies=[]
    for index in (1,2):
        command={'operation_id':f'owned-template-copy-{index}','name':f'owned-template-copy-{index}','template_snapshot':receipt['content']}
        response=await http.post('/v1/agents',json=command);assert response.status==201
        copy=await response.json();copies.append(copy['id'])
        assert copy['metadata']['allowed_tools']==[] and copy['role']=='specialist'
        assert copy['metadata']['template']['version']==payload['version']
        assert copy['metadata']['template']['source_bot']==payload['source_bot']
        assert copy['metadata']['template']['provenance']=='owner_provided_unverified'
        assert 'account_secret' not in copy['metadata']
        assert await (await http.post('/v1/agents',json=command)).json()==copy
    assert len(set(copies))==2
    denied=await http.post('/v1/agents',json={'name':'owned-authority-copy','template_snapshot':receipt['content'],'metadata':{'allowed_tools':['terminal']}})
    assert denied.status==400 and registry.get_agent('native:owned-authority-copy') is None
    assert registry.get_agent(record.id).to_dict()==before
    assert (await http.get(path,headers=client_headers('jaegerd'))).status==403
    assert (await http.get(path,headers=client_headers('a2a'))).status==403
    assert (await http.get(path.replace('revision=0','revision=1'))).status==409
    assert (await http.get('/v1/agents/native:builder/template-export?revision=0')).status==403
    assert len(app.store.list_messages('owned-template-history')['messages'])==1


@pytest.mark.asyncio
async def test_export_refuses_potential_secret_prompt_instead_of_masked_copy(gw,tmp_path,monkeypatch):
    app,http=gw;registry=AgentRegistry(tmp_path/'owned-secret-template')
    monkeypatch.setattr(app,'_registry',lambda:registry)
    record=registry.create_agent('owned-export',role='specialist',metadata={'operator_instructions':'Use password=fixture-secret-value'})
    response=await http.get('/v1/agents/'+record.id+'/template-export?revision=0')
    assert response.status==400 and 'fixture-secret-value' not in await response.text()
    assert registry.get_agent(record.id).metadata['operator_instructions']=='Use password=fixture-secret-value'


@pytest.mark.asyncio
async def test_unsafe_snapshot_has_known_rejection_receipt_without_private_intent_copy(gw,tmp_path,monkeypatch):
    app,http=gw;registry=AgentRegistry(tmp_path/'owned-rejected-import')
    monkeypatch.setattr(app,'_registry',lambda:registry)
    source=registry.create_agent('owned-source',role='specialist')
    exported=await (await http.get('/v1/agents/'+source.id+'/template-export?revision=0')).json()
    content=json.loads(exported['content']);content['settings']['instructions']='password=fixture-sensitive-rejected'
    body={'operation_id':'owned-rejected-template','name':'owned-rejected-copy','template_snapshot':json.dumps(content)}
    response=await http.post('/v1/agents',json=body);assert response.status==400
    row=app.store.control_operation(body['operation_id'])
    assert row['receipt']['ok'] is False
    assert 'fixture-sensitive-rejected' not in json.dumps(row)
    assert registry.get_agent('native:owned-rejected-copy') is None
    assert (await http.post('/v1/agents',json=body)).status==400
    assert (await (await http.get('/v1/control-operations/'+body['operation_id'])).json())['receipt']==row['receipt']
