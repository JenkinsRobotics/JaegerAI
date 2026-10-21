"""Explicit resources through local SDK stand-ins; no external provider/auth."""
from types import SimpleNamespace
import hashlib
import json
import pytest
from jaeger_ai.plugins.mcp import client as mcp,resources


@pytest.fixture
def registry(monkeypatch):
    secret='fixture-transport-secret-NEVER-RETURN'
    calls=[]
    class LocalSDK:
        resources_advertised=True
        def __init__(self,config):self.config=config
        async def connect(self):return []
        async def close(self,*,strict=False):pass
        async def list_resources(self,cursor=None):
            calls.append(('list',cursor))
            return SimpleNamespace(resources=[SimpleNamespace(uri='fixture://resource?private='+secret,name='Name '+secret,description='Description '+secret,mimeType='text/'+secret)],nextCursor='private-page-'+secret if cursor is None else None)
        async def read_resource(self,uri):
            calls.append(('read',uri))
            return SimpleNamespace(contents=[SimpleNamespace(text='Owned reference '+secret)])
    monkeypatch.setattr(mcp,'_MCPClient',LocalSDK)
    registry=mcp.MCPRegistry();registry.add_server(mcp.MCPServerConfig(name='owned-resource-fixture',headers={'Authorization':secret}))
    monkeypatch.setattr(mcp,'_GLOBAL_REGISTRY',registry)
    yield registry,registry.control_id('owned-resource-fixture'),calls,secret
    registry.shutdown();registry._loop.close()


def test_every_catalog_string_is_redacted_and_uris_cursors_remain_private(registry):
    owner,sid,calls,secret=registry
    catalog=resources.listing(owner,sid)
    assert secret not in json.dumps(catalog)
    row=catalog['resources'][0]
    assert all(secret not in row[field] and '********' in row[field] for field in ('title','description','mime'))
    assert 'uri' not in row and 'private-page' not in catalog['next_page']
    assert catalog['next_page'] and catalog['no_grants']
    next_page=resources.listing(owner,sid,page=catalog['next_page'])
    assert calls[-1]==('list','private-page-'+secret) and next_page['next_page'] is None
    with pytest.raises(ValueError):resources.read(owner,sid,'arbitrary-not-listed',limit=2000)
    assert len(calls)==2
    snapshot=resources.read(owner,sid,row['id'],limit=2000)
    assert secret not in json.dumps(snapshot) and snapshot['redacted']
    assert snapshot['digest']==hashlib.sha256(snapshot['text'].encode()).hexdigest()
    assert snapshot['authority']=='reference_data_only'


@pytest.mark.asyncio
async def test_resource_http_reviewed_import_uses_library_owner_and_no_duplicate_source_text(registry,tmp_path,monkeypatch):
    from aiohttp.test_utils import TestClient,TestServer
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    from jaeger_ai.core.gateway.caller_auth import client_headers
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_ai.core.instance.schemas import Config,ModelConfig,dump_yaml
    layout=InstanceLayout(root=tmp_path/'instance');layout.ensure_dirs();dump_yaml(layout.config_path,Config(instance_name='resource-fixture',model=ModelConfig(model_path='/dev/null')))
    monkeypatch.setenv('JAEGER_INSTANCE_DIR',str(layout.root))
    owner,sid,calls,secret=registry
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    base='/v1/runtime/mcp/'+sid+'/resources/'
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        listed=await http.post(base+'list',json={'operation_id':'owned-list','page':None});assert listed.status==200
        catalog=(await listed.json())['result']['catalog'];rid=catalog['resources'][0]['id']
        assert secret not in json.dumps(catalog)
        assert secret not in json.dumps(gateway.store.control_operation('owned-list'))
        read=await http.post(base+'read',json={'operation_id':'owned-read','resource_id':rid});assert read.status==200
        descriptor=(await read.json())['result']['snapshot']
        assert secret not in json.dumps(descriptor)
        snapshot=await (await http.get(base+'snapshots/'+descriptor['id'])).json()
        assert 'Owned reference' in snapshot['text'] and secret not in str(snapshot)
        saved_receipt=gateway.store.control_operation('owned-read')
        assert secret not in json.dumps(saved_receipt)
        assert 'Owned reference' not in json.dumps(saved_receipt) and 'text' not in saved_receipt['receipt']['result']['snapshot']
        from jaeger_ai.features.knowledge_library.tools import _library
        library=_library()
        try:assert library.managed_documents()==[]
        finally:library.close()
        body={'operation_id':'owned-import','snapshot_id':snapshot['id'],'expected_digest':snapshot['digest']}
        response=await http.post(base+'import',json=body);assert response.status==200
        imported=await response.json();document=imported['result']['document']
        repeated=await http.post(base+'import',json=body);assert await repeated.json()==imported
        assert [kind for kind,_ in calls]==['list','read']
        library=_library()
        try:
            assert len(library.managed_documents())==1
            actual=library.managed_document(document['id'])
            assert actual['content']==snapshot['text'] and actual['digest']==snapshot['digest']
            assert actual['provenance']['resource_id']==rid and actual['provenance']['redacted']
        finally:library.close()
        assert gateway.store.list_requests()==[] and gateway.store.agent_presentation()=={}
        assert secret not in json.dumps(imported)
        assert (await http.post(base+'read',json={'operation_id':'owned-bad','resource_id':'0'*32})).status==409
        assert [kind for kind,_ in calls]==['list','read']
    async with TestClient(TestServer(gateway.app),headers=client_headers('a2a')) as http:
        assert (await http.post(base+'list',json={'operation_id':'forbidden-list','page':None})).status==403
        assert (await http.get(base+'snapshots/'+snapshot['id'])).status==403
