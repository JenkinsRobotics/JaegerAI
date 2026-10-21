import pytest
from aiohttp.test_utils import TestClient, TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers
from jaeger_ai.features.knowledge_library import KnowledgeLibrary
from jaeger_ai.features.knowledge_library import tools


@pytest.mark.asyncio
async def test_managed_http_revisions_and_readonly_caller_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, '_library', lambda: KnowledgeLibrary(tmp_path/'library.db'))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.db'))
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        body = {'operation_id': 'owned-create', 'title': 'Owned document', 'content': 'Safe text'}
        response = await client.post('/v1/library/documents', json=body)
        assert response.status == 200
        receipt = await response.json(); document_id = receipt['document']['id']
        assert (await (await client.post('/v1/library/documents', json=body)).json()) == receipt
        assert (await client.post('/v1/library/documents', json={**body, 'content': 'Other'})).status == 400
        saved = await client.post(f'/v1/library/documents/{document_id}/save', json={'operation_id': 'owned-save', 'title': 'Owned document', 'content': 'New text', 'expected_revision': 1})
        assert saved.status == 200
        stale = await client.post(f'/v1/library/documents/{document_id}/save', json={'operation_id': 'owned-stale', 'title': 'Lost edit', 'content': 'Wrong', 'expected_revision': 1})
        assert stale.status == 409
        assert (await (await client.get(f'/v1/library/documents/{document_id}')).json())['content'] == 'New text'
        archive = await client.post(f'/v1/library/documents/{document_id}/archive', json={'operation_id': 'owned-archive', 'expected_revision': 2})
        assert archive.status == 200
        assert (await (await client.get('/v1/library/search?q=New')).json())['results'] == []
        assert len((await (await client.get(f'/v1/library/documents/{document_id}/versions')).json())['versions']) == 3
    async with TestClient(TestServer(gateway.app), headers=client_headers('a2a')) as client:
        assert (await client.post('/v1/library/documents', json={'operation_id': 'forbidden', 'title': 'No', 'content': 'No'})).status == 403
        assert (await client.get(f'/v1/library/documents/{document_id}')).status == 403


@pytest.mark.asyncio
async def test_document_write_unknown_is_not_replayed(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, '_library', lambda: KnowledgeLibrary(tmp_path/'library.db'))
    library = KnowledgeLibrary(tmp_path/'library.db')
    doc = library.create_document(title='Owned', content='Before', command_id='seed')
    library.close()
    original = KnowledgeLibrary.save_document
    writes = []
    def response_lost(self, *args, **kwargs):
        writes.append(True)
        original(self, *args, **kwargs)
        raise OSError('Lost after commit')
    monkeypatch.setattr(KnowledgeLibrary, 'save_document', response_lost)
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.db'))
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        path = f'/v1/library/documents/{doc["id"]}/save'
        body = {'operation_id': 'owned-lost', 'title': 'Owned', 'content': 'After', 'expected_revision': 1}
        assert (await client.post(path, json=body)).status == 503
        assert (await client.post(path, json=body)).status == 409
        assert len(writes) == 1
        current = await (await client.get(f'/v1/library/documents/{doc["id"]}')).json()
        assert current['content'] == 'After' and current['revision'] == 2
        assert gateway.store.control_operation('owned-lost')['receipt'] is None


@pytest.mark.asyncio
async def test_gateway_library_uses_canonical_bound_instance_without_cli_pipeline(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_agent.core.workspace import bind
    layout = InstanceLayout(root=tmp_path/'owned-instance')
    layout.ensure_dirs()
    monkeypatch.setenv('JAEGER_INSTANCE_DIR', str(layout.root))
    bind(layout)
    # No _library replacement: exercise the real owner used by the HTTP route.
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'owned-gateway.sqlite3'))
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        response = await client.post('/v1/library/documents', json={'operation_id':'owned-bound-library', 'title':'Owned bound document', 'content':'Canonical instance library text'})
        assert response.status == 200, await response.text()
        document_id = (await response.json())['document']['id']
        assert (await (await client.get('/v1/library')).json())['limits']['document_bytes'] == 2000000
        assert (layout.memory_dir/'library.db').is_file()
        read = await client.get('/v1/library/documents/'+document_id)
        assert (await read.json())['content'] == 'Canonical instance library text'
        results = await client.get('/v1/library/search?q=Canonical')
        assert any(row['id'] == document_id for row in (await results.json())['results'])


@pytest.mark.asyncio
async def test_custom_agent_knowledge_pins_context_and_preserves_policy(tmp_path, monkeypatch):
    import asyncio
    from jaeger_ai.core.instance.instance import InstanceLayout
    from jaeger_agent.core.workspace import bind
    from jaeger_ai.features.knowledge_library.agent_context import materialize
    layout = InstanceLayout(root=tmp_path/'owned-knowledge-instance'); layout.ensure_dirs()
    monkeypatch.setenv('JAEGER_INSTANCE_DIR', str(layout.root)); bind(layout)
    store = GatewaySessionStore(tmp_path/'owned-knowledge-gateway.sqlite3')
    gateway = JaegerGatewayApp(store=store)
    seen = []
    async def model_boundary(prompt, **kwargs):
        seen.append(kwargs['system_prompt']); return 'Owned knowledge result'
    gateway._ollama_chat = model_boundary
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        created = await client.post('/v1/agents', json={'name':'owned-knowledge', 'role':'specialist', 'operation_id':'owned-knowledge-agent'})
        assert created.status == 201
        agent = await created.json(); path = '/v1/agents/'+agent['id']+'/knowledge'
        doc_response = await client.post('/v1/library/documents', json={'operation_id':'owned-knowledge-doc', 'title':'Owned reference', 'content':'ORIGINAL PINNED REFERENCE'})
        doc = (await doc_response.json())['document']; document_id = doc['id']
        assigned = await client.patch(path, json={'expected_revision':0,'document_ids':[document_id]})
        assert assigned.status == 200
        binding = await assigned.json()
        assert binding['documents'] == [{'id':document_id,'revision':1,'digest':doc['digest']}]
        assert binding['limits'] == {'max_documents':8,'context_chars':32000}
        configured = await client.patch('/v1/agents/'+agent['id']+'/configuration',json={'expected_revision':1,'settings':{'specialty':'Evidence','summary':'Owned summary','instructions':'Use supplied reference'}})
        assert configured.status == 200
        assert gateway._registry().get_agent(agent['id']).metadata['knowledge_documents'] == binding['documents']
        stale = await client.patch(path, json={'expected_revision':0,'document_ids':[]})
        assert stale.status == 409
        protected = await client.patch('/v1/agents/native:builder/knowledge', json={'expected_revision':0,'document_ids':[document_id]})
        assert protected.status == 403
        for invalid in ([{'path':'/private/file'}], [document_id,document_id], ['../private/file']):
            assert (await client.patch(path, json={'expected_revision':1,'document_ids':invalid})).status == 400
        await client.post('/v1/library/documents/'+document_id+'/save', json={'operation_id':'owned-update-knowledge','expected_revision':1,'title':'Changed reference','content':'NEW UNASSIGNED REVISION'})
        bound = gateway._registry().get_agent(agent['id'])
        context = materialize(bound, actor='owner:webui')
        assert 'ORIGINAL PINNED REFERENCE' in context['text'] and 'NEW UNASSIGNED REVISION' not in context['text']
        with pytest.raises(PermissionError):
            materialize(bound, actor='a2a')
        sid = 'owned-knowledge-session'; store.ensure_session(sid,metadata={'agent_id':agent['id'],'interaction_tier':'chat'})
        response = await client.post('/v1/sessions/'+sid+'/turns', json={'request_id':'owned-knowledge-turn','text':'Summarize supplied reference','interaction_tier':'chat'})
        assert response.status == 200
        for _ in range(200):
            row = store.get_request('owned-knowledge-turn')
            if row['status'] in {'completed','failed','execution_unknown','cancelled'}: break
            await asyncio.sleep(.05)
        assert row['status'] == 'completed', row.get('result')
        assert len(seen) == 1 and 'ORIGINAL PINNED REFERENCE' in seen[0] and 'NEW UNASSIGNED REVISION' not in seen[0]
        parts = store.get_session(sid)['messages'][-1]['parts']
        assert any(part['type']=='knowledge' and part['documents'][0]['revision']==1 for part in parts)
        await client.post('/v1/library/documents/'+document_id+'/archive',json={'operation_id':'owned-archive-knowledge','expected_revision':2})
        with pytest.raises(RuntimeError):
            materialize(bound,actor='owner:webui')
        removed = await client.patch(path,json={'expected_revision':2,'document_ids':[]})
        assert removed.status == 200 and (await removed.json())['documents']==[]
        current = gateway._registry().get_agent(agent['id'])
        assert current.id == agent['id'] and current.role.value == 'specialist'
        assert current.metadata.get('allowed_tools') == agent['metadata'].get('allowed_tools')
        assert store.primary_agent_id() == 'native:jaeger'
        assert len(store.get_session(sid)['messages']) == 2
    async with TestClient(TestServer(gateway.app), headers=client_headers('a2a')) as client:
        assert (await client.get(path)).status == 403
