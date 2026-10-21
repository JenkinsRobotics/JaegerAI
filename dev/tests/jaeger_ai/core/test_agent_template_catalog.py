"""Registry-owned retained local templates. Owned disposable agents only."""
import json

import pytest

from jaeger_ai.core.agent_registry import AgentRegistry
from jaeger_ai.core.gateway.caller_auth import client_headers

pytest_plugins=('dev.tests.jaeger_ai.core.test_sessions_contract',)


@pytest.mark.asyncio
async def test_saved_versions_reopen_select_hide_restore_preserve_source_authority(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-catalog';registry=AgentRegistry(root)
    source=registry.create_agent('owned-source',role='specialist',metadata={'operator_instructions':'Version one','allowed_tools':['owned-original'],'account':'private-not-copied'})
    monkeypatch.setattr(app,'_registry',lambda:AgentRegistry(root))
    app.store.ensure_session('owned-source-history',metadata={'agent_id':source.id})
    app.store.append_message('owned-source-history','user','Retain this private history')
    path='/v1/agents/'+source.id+'/templates'
    save={'operation_id':'owned-catalog-save1','action':'save','expected_revision':0,'expected_catalog_revision':0}
    first=await (await http.post(path,json=save)).json();assert first['outcome']=='saved'
    assert await (await http.post(path,json=save)).json()==first
    assert (await http.get(path,headers=client_headers('jaegerd'))).status==403
    assert (await http.post(path,json=save,headers=client_headers('a2a'))).status==403
    registry=AgentRegistry(root)
    registry.configure_specialist(source.id,{'specialty':'second','summary':'second','instructions':'Version two'},0)
    second=await (await http.post(path,json={**save,'operation_id':'owned-catalog-save2','expected_revision':1,'expected_catalog_revision':1})).json()
    assert second['result']['catalog_revision']==2 and [v['version'] for v in second['result']['versions']]==[1,2]
    saved=[t for t in (await (await http.get('/v1/agent-templates')).json())['templates'] if t['id']=='saved:'+source.id]
    assert [v['instructions'] for v in saved]==['Version one','Version two']
    copies=[]
    for index in (1,2):
        command={'operation_id':f'owned-catalog-copy{index}','name':f'owned-copy{index}','template_id':'saved:'+source.id,'template_version':1}
        response=await http.post('/v1/agents',json=command);assert response.status==201
        copy=await response.json();copies.append(copy['id'])
        assert copy['role']=='specialist' and copy['metadata']['allowed_tools']==[]
        assert copy['metadata']['operator_instructions']=='Version one'
        assert copy['metadata']['template']['version']==1 and copy['metadata']['template']['source_bot']['agent_id']==source.id
        assert 'account' not in copy['metadata']
    assert len(set(copies))==2
    visibility={'operation_id':'owned-catalog-hide','action':'visibility','hidden':True,'expected_catalog_revision':2}
    assert (await (await http.post(path,json=visibility)).json())['outcome']=='saved'
    assert not [t for t in (await (await http.get('/v1/agent-templates')).json())['templates'] if t['id']=='saved:'+source.id]
    response=await http.post('/v1/agents',json={'operation_id':'owned-hidden-copy','name':'owned-hidden-copy','template_id':'saved:'+source.id,'template_version':1})
    assert response.status==400
    restored=await (await http.post(path,json={**visibility,'operation_id':'owned-catalog-restore','hidden':False,'expected_catalog_revision':3})).json()
    assert len(restored['result']['versions'])==2
    final=AgentRegistry(root).get_agent(source.id)
    assert final.metadata['operator_instructions']=='Version two' and final.metadata['configuration_revision']==1
    assert final.metadata['allowed_tools']==['owned-original'] and final.metadata['account']=='private-not-copied'
    assert final.role==source.role and final.id==source.id
    assert app.store.list_messages('owned-source-history')['messages'][0]['content']=='Retain this private history'
    assert AgentRegistry(root).get_agent(copies[0]).metadata['operator_instructions']=='Version one'


@pytest.mark.asyncio
async def test_catalog_lost_ack_recovers_without_reexecuting_and_stale_writer_rejects(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-lost-catalog';registry=AgentRegistry(root)
    source=registry.create_agent('owned-source',role='specialist',metadata={'operator_instructions':'Owned prompt'})
    stale=AgentRegistry(root)
    monkeypatch.setattr(app,'_registry',lambda:AgentRegistry(root))
    save=AgentRegistry.save_template
    def lost(self,*a,**k):save(self,*a,**k);raise OSError('Lost response')
    monkeypatch.setattr(AgentRegistry,'save_template',lost)
    path='/v1/agents/'+source.id+'/templates';body={'operation_id':'owned-lost-template','action':'save','expected_revision':0,'expected_catalog_revision':0}
    assert (await http.post(path,json=body)).status==503
    monkeypatch.setattr(AgentRegistry,'save_template',lambda *a,**k:pytest.fail('No replay'))
    receipt=await (await http.get('/v1/agent-template-operations/'+body['operation_id'])).json()
    assert receipt['outcome']=='saved' and receipt['recovered'] and len(receipt['result']['versions'])==1
    assert await (await http.post(path,json=body)).json()==receipt
    stale._data['active_id']=source.id
    with pytest.raises(ValueError,match='current file retained'):stale._save()
    assert len(AgentRegistry(root).get_agent(source.id).metadata['template_catalog']['versions'])==1


def test_planning_edit_cannot_overwrite_newer_registry_or_retained_versions(tmp_path):
    root=tmp_path/'owned-concurrent-catalog';registry=AgentRegistry(root)
    source=registry.create_agent('owned-source',role='specialist')
    replacement=json.loads(registry.path.read_text());replacement['agents'][source.id]['metadata']['operator_instructions']='Newer edit'
    def edit(_data,_revision):registry.path.write_text(json.dumps(replacement))
    with pytest.raises(ValueError,match='current file retained'):
        registry.save_template(source.id,0,0,before_commit=edit)
    assert json.loads(registry.path.read_text())==replacement
    assert 'template_catalog' not in AgentRegistry(root).get_agent(source.id).metadata


@pytest.mark.asyncio
async def test_diverged_catalog_outcome_remains_unknown_and_blocks_new_nonce(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-diverged-catalog';registry=AgentRegistry(root)
    source=registry.create_agent('owned-source',role='specialist')
    monkeypatch.setattr(app,'_registry',lambda:AgentRegistry(root))
    save=AgentRegistry.save_template;calls=[]
    def lost(self,*a,**k):
        calls.append(1);save(self,*a,**k)
        # An owned later edit makes the original result unprovable; never replay it.
        data=json.loads(self.path.read_text());data['agents'][source.id]['metadata']['template_catalog']['hidden']=True
        self.path.write_text(json.dumps(data));raise OSError('Unknown after divergence')
    monkeypatch.setattr(AgentRegistry,'save_template',lost)
    path='/v1/agents/'+source.id+'/templates';body={'operation_id':'owned-diverged-template','action':'save','expected_revision':0,'expected_catalog_revision':0}
    assert (await http.post(path,json=body)).status==503
    assert (await (await http.get('/v1/agent-template-operations/'+body['operation_id'])).json())['outcome']=='unknown'
    assert (await (await http.post(path,json=body)).json())['outcome']=='unknown'
    assert (await http.post(path,json={**body,'operation_id':'owned-new-template'})).status==409
    rejected=await (await http.get('/v1/agent-template-operations/owned-new-template')).json()
    assert rejected['outcome']=='rejected'
    assert (await (await http.post(path,json={**body,'operation_id':'owned-new-template'})).json())==rejected
    assert calls==[1] and AgentRegistry(root).get_agent(source.id).metadata['template_catalog']['hidden'] is True


def test_saving_an_existing_hidden_snapshot_does_not_silently_restore_visibility(tmp_path):
    registry=AgentRegistry(tmp_path/'owned-hidden-template')
    source=registry.create_agent('owned-source',role='specialist')
    registry.save_template(source.id,0,0)
    registry.set_template_hidden(source.id,True,1)
    result=registry.save_template(source.id,0,2)
    assert result['hidden'] is True and len(result['versions'])==1
    assert registry.saved_templates()==[]


@pytest.mark.asyncio
async def test_corrupt_saved_source_is_retained_and_does_not_block_other_templates(gw,tmp_path,monkeypatch):
    app,http=gw;root=tmp_path/'owned-corrupt-source';registry=AgentRegistry(root)
    source=registry.create_agent('owned-source',role='specialist')
    registry.save_template(source.id,0,0)
    data=json.loads(registry.path.read_text());data['agents'][source.id]['metadata']['template_catalog']['versions'][0]['sha256']='not-original'
    registry.path.write_text(json.dumps(data));original=registry.path.read_bytes()
    monkeypatch.setattr(app,'_registry',lambda:AgentRegistry(root))
    result=await (await http.get('/v1/agent-templates')).json()
    assert result['unavailable_saved_sources']==[source.id] and result['templates']
    assert not any(t['id']=='saved:'+source.id for t in result['templates'])
    assert (await http.get('/v1/agents/'+source.id+'/templates')).status==409
    template=result['templates'][0]
    response=await http.post('/v1/agents',json={'operation_id':'owned-unaffected-template','name':'owned-unaffected','template_id':template['id'],'template_version':template['version']})
    assert response.status==201
    retained=json.loads(registry.path.read_text())['agents'][source.id]
    assert retained==json.loads(original)['agents'][source.id]


def test_catalog_preserves_unrelated_registry_extensions_and_refuses_corrupt_source(tmp_path):
    registry=AgentRegistry(tmp_path/'owned-extended-registry');source=registry.create_agent('owned-source',role='specialist')
    data=json.loads(registry.path.read_text());data['owner_extension']={'retained':True};data['agents'][source.id]['future_extension']={'retained':True}
    registry.path.write_text(json.dumps(data));registry.save_template(source.id,0,0)
    saved=json.loads(registry.path.read_text())
    assert saved['owner_extension']==data['owner_extension'] and saved['agents'][source.id]['future_extension']==data['agents'][source.id]['future_extension']
    registry.path.write_text('{"version":1,"agents":{"unreadable":"retain this"}}')
    broken=AgentRegistry(registry.root)
    with pytest.raises(RuntimeError,match='original retained'):broken._save()
    assert registry.path.read_text()=='{"version":1,"agents":{"unreadable":"retain this"}}'
