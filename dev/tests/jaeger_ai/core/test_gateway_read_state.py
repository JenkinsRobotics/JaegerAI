import pytest
from aiohttp.test_utils import TestClient, TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


@pytest.mark.asyncio
async def test_unread_is_durable_scoped_idempotent_and_clearable(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    store = GatewaySessionStore(tmp_path / 'gateway.db')
    store.ensure_session('owned', metadata={'custom': 'keep'})
    store.ensure_session('other')
    store.admit_request('owned', 'Question', request_id='request')
    store.complete_request('request', status='completed', result={'output': 'Answer'}, assistant_text='Answer')
    updated = store.get_session('owned')['updated_at']
    gateway = JaegerGatewayApp(store=store)
    path = '/v1/sessions/owned/read-state'
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        assert await (await client.get(path)).json() == {'unread': None, 'event_id': 0}
        body = {'request_id': 'request', 'role': 'user'}
        first = await (await client.post(path, json=body)).json()
        assert first['unread'] == body
        assert first['event_id'] > 0
        assert await (await client.post(path, json=body)).json() == first
        assert (await client.post('/v1/sessions/other/read-state', json=body)).status == 404
        assert (await client.get('/v1/sessions/missing/read-state')).status == 404
        for malformed in [None, [], {}, {**body, 'role': []}, {**body, 'role': 'system'}, {**body, 'request_id': 1}, {**body, 'extra': True}]:
            assert (await client.post(path, json=malformed)).status == 400
        body['role'] = 'assistant'
        changed = await (await client.post(path, json=body)).json()
        assert changed['event_id'] > first['event_id']
        assert GatewaySessionStore(store.path).message_read_state('owned') == changed
        assert next(row for row in store.list_sessions() if row['session_id'] == 'owned')['unread'] == body
        assert store.get_session('owned')['unread'] == body
        assert store.get_session('owned')['updated_at'] == updated
        assert store.get_session('owned')['metadata']['custom'] == 'keep'
        assert store.branch_session('owned')['unread'] is None
        cleared = await (await client.delete(path)).json()
        assert cleared['unread'] is None
        assert cleared['event_id'] > changed['event_id']
        assert await (await client.delete(path)).json() == cleared
        assert GatewaySessionStore(store.path).message_read_state('owned') == cleared
        assert store.message_read_state('other') == {'unread': None, 'event_id': 0}


@pytest.mark.parametrize('bad', [None, [], 'legacy', {'unread': None}, {'unread': {'role': [], 'request_id': 'r'}, 'event_id': 1}])
def test_malformed_imported_marker_cannot_break_history(tmp_path, bad):
    store = GatewaySessionStore(tmp_path / 'gateway.db')
    store.ensure_session('imported', metadata={'message_read_state': bad})
    assert store.message_read_state('imported') == {'unread': None, 'event_id': 0}
    assert store.get_session('imported')['unread'] is None
    assert store.list_sessions()[0]['unread'] is None
    assert store.set_message_read_state('imported', None)['unread'] is None
