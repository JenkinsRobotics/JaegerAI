"""Real workflow Library/Task owners; no external execution or grants."""
import pytest
from aiohttp.test_utils import TestClient, TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, ModelConfig, dump_yaml


@pytest.mark.asyncio
async def test_workflow_versions_proposal_replay_and_recoverable_archive(tmp_path, monkeypatch):
    layout=InstanceLayout(root=tmp_path/'instance');layout.ensure_dirs();dump_yaml(layout.config_path,Config(instance_name='workflow-fixture',model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR',str(layout.root))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
        catalog=await (await client.get('/v1/workflows')).json()
        definition={'format':catalog['format'],'name':'Owned workflow','description':'Safe fixture plan','steps':[{'title':'Read supplied data','instruction':'Summarize supplied material; do not use external tools.'}]}
        response=await client.post('/v1/workflows',json={'operation_id':'owned-wf-create','definition':definition})
        assert response.status==200
        original=await response.json();doc=original['workflow'];document_id=doc['id']
        assert doc['revision']==1 and not doc['archived']
        gateway.store.ensure_session('owned-wf-home',metadata={'agent_id':'native:builder'})
        body={'operation_id':'owned-wf-proposal','expected_revision':1,'session_id':'owned-wf-home'}
        proposed=await client.post('/v1/workflows/'+document_id+'/propose',json=body)
        assert proposed.status==200
        receipt=await proposed.json();task=gateway.task_owner.store.get_task(receipt['task']['task_id'])
        assert task.state.value=='paused' and task.provenance['authorized'] is False
        assert task.provenance['workflow_revision']==1 and task.provenance['workflow_digest']==doc['digest']
        assert task.payload['execution']['caller']=='owner:webui'
        assert len(gateway.store.list_pending_approvals())==1
        assert gateway.store.list_requests()==[]
        changed={**definition,'description':'New saved instructions'}
        saved=await client.post('/v1/workflows/'+document_id+'/save',json={'operation_id':'owned-wf-edit','expected_revision':1,'definition':changed})
        assert saved.status==200 and (await saved.json())['workflow']['revision']==2
        repeated=await client.post('/v1/workflows/'+document_id+'/propose',json=body)
        assert await repeated.json()==receipt
        assert len(gateway.task_owner.store.list_tasks())==1
        assert 'New saved instructions' not in gateway.task_owner.store.get_task(task.task_id).goal
        stale=await client.post('/v1/workflows/'+document_id+'/save',json={'operation_id':'owned-wf-stale','expected_revision':1,'definition':definition})
        assert stale.status==409
        archived=await client.post('/v1/workflows/'+document_id+'/archive',json={'operation_id':'owned-wf-archive','expected_revision':2})
        assert archived.status==200 and (await archived.json())['workflow']['archived']
        blocked=await client.post('/v1/workflows/'+document_id+'/propose',json={'operation_id':'owned-wf-blocked','expected_revision':3,'session_id':'owned-wf-home'})
        assert blocked.status==409
        restored=await client.post('/v1/workflows/'+document_id+'/restore',json={'operation_id':'owned-wf-restore','expected_revision':3})
        assert restored.status==200 and not (await restored.json())['workflow']['archived']
        assert len(gateway.task_owner.store.list_tasks())==1
        assert len(gateway.store.list_pending_approvals())==1
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as client:
        assert (await client.get('/v1/workflows')).status==403
        assert (await client.post('/v1/workflows',json={'operation_id':'forbidden','definition':definition})).status==403


@pytest.mark.asyncio
async def test_workflow_invalid_grants_and_unknown_are_never_executed(tmp_path,monkeypatch):
    layout=InstanceLayout(root=tmp_path/'instance');layout.ensure_dirs();dump_yaml(layout.config_path,Config(instance_name='workflow-invalid',model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR',str(layout.root))
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as client:
        format=(await (await client.get('/v1/workflows')).json())['format']
        invalid={'format':format,'name':'Unsafe declaration','description':'Fixture','steps':[{'title':'Unsafe','instruction':'No','allowed_tools':['terminal']}]}
        rejected=await client.post('/v1/workflows',json={'operation_id':'owned-wf-invalid','definition':invalid})
        assert rejected.status==400
        assert gateway.store.control_operation('owned-wf-invalid')['receipt']['ok'] is False
        assert (await (await client.get('/v1/workflows')).json())['workflows']==[]
        definition={'format':format,'name':'Unknown fixture','description':'No execution','steps':[{'title':'Step','instruction':'Read supplied data'}]}
        body={'operation_id':'owned-wf-unknown','definition':definition}
        gateway.store.reserve_control_operation('owned-wf-unknown',{'action':'workflow.create','id':'','body':body})
        unknown=await client.post('/v1/workflows',json=body)
        assert unknown.status==409 and (await unknown.json())['execution_unknown'] is True
        assert (await (await client.get('/v1/workflows')).json())['workflows']==[]
        assert gateway.task_owner.store.list_tasks()==[]
