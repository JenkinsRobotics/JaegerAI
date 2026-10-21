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
