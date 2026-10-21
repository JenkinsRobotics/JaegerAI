import pytest
from aiohttp.test_utils import TestClient, TestServer
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.caller_auth import client_headers


@pytest.mark.asyncio
async def test_request_identity_reactions_role_scope_replay_and_reopen(tmp_path):
    store = GatewaySessionStore(tmp_path/'gateway.db')
    store.ensure_session('owned'); store.ensure_session('other')
    admission = store.admit_request('owned', 'Owned question', request_id='owned-request')
    store.complete_request('owned-request', status='completed', result={'output':'Owned answer'}, assistant_text='Owned answer')
    for message in store.list_messages('owned')['messages']:
        assert message['request_id'] == 'owned-request'
        assert message['turn_id'] == admission['turn_id']
    assert {m['request_id'] for m in store.get_session('owned')['messages']} == {'owned-request'}
    gateway = JaegerGatewayApp(store=store)
    async with TestClient(TestServer(gateway.app), headers=client_headers('webui')) as client:
        body = {'request_id':'owned-request', 'role':'user', 'emoji':'👍', 'active':True}
        first_response = await client.post('/v1/sessions/owned/feedback', json=body)
        assert first_response.status == 200
        first = await first_response.json()
        repeated = await (await client.post('/v1/sessions/owned/feedback', json=body)).json()
        assert repeated['event_id'] == first['event_id']
        assert first['reactions'] == {'owned-request|user':['👍']}
        assistant = await (await client.post('/v1/sessions/owned/feedback', json={**body,'role':'assistant','emoji':'🎉'})).json()
        assert assistant['reactions']['owned-request|assistant'] == ['🎉']
        assert (await client.post('/v1/sessions/other/feedback', json=body)).status == 404
        assert (await client.post('/v1/sessions/owned/feedback', json={**body,'role':[]})).status == 400
        assert (await client.post('/v1/sessions/owned/feedback', json={**body,'emoji':'not-supported'})).status == 400
        removed = await (await client.post('/v1/sessions/owned/feedback', json={**body,'active':False})).json()
        assert removed['reactions']['owned-request|user'] == []
        assert removed['reactions']['owned-request|assistant'] == ['🎉']
    reopened = GatewaySessionStore(store.path)
    assert reopened.message_reactions('owned')['reactions']['owned-request|assistant'] == ['🎉']
    assert reopened.message_reactions('other')['reactions'] == {}
