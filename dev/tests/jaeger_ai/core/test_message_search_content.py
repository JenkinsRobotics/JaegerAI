"""Real scoped store and authenticated message reads; no model or metadata mutation."""
import pytest
from aiohttp.test_utils import TestClient,TestServer
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.caller_auth import client_headers


def test_unicode_casefold_offsets_bounded_complete_read_and_foreign_scope(tmp_path):
    store=GatewaySessionStore(tmp_path/'gateway.sqlite3')
    store.ensure_session('owned',metadata={'agent_id':'native:owned'})
    store.ensure_session('foreign',metadata={'agent_id':'native:foreign'})
    text='ß'*11000+' Straße Σίσυφος '+('Owned tail '*1000)
    store.append_message('owned','user',text)
    store.append_message('foreign','user','Straße PRIVATE-FOREIGN')
    page=store.search_agent_messages('native:owned','STRASSE')
    assert page['matching']=='literal_unicode_casefold' and len(page['matches'])==1
    hit=page['matches'][0]
    assert hit['match_offset']==11001 and 'Straße' in hit['snippet']
    assert hit['truncated'] and 'Straße' not in hit['content']
    assert store.search_agent_messages('native:owned','ΣΊΣΥΦΟΣ')['matches']
    chunks=[];offset=0
    while True:
        part=store.agent_message_content('native:owned',int(hit['message_id']),offset=offset,expected_revision=hit['content_revision'])
        assert len(part['content'])<=8000
        chunks.append(part['content'])
        if part['next_offset'] is None:break
        assert part['next_offset']>offset;offset=part['next_offset']
    assert ''.join(chunks)==text
    assert store.agent_message_content('native:foreign',int(hit['message_id'])) is None
    with pytest.raises(ValueError,match='revision changed'):store.agent_message_content('native:owned',int(hit['message_id']),expected_revision='stale')
    with pytest.raises(ValueError):store.agent_message_content('native:owned',2**90)
    assert store.get_session('owned')['metadata']=={'agent_id':'native:owned'}
    assert store.list_requests()==[]


@pytest.mark.asyncio
async def test_authenticated_full_message_read_checks_registry_and_scope(tmp_path):
    gateway=JaegerGatewayApp(store=GatewaySessionStore(tmp_path/'gateway.sqlite3'))
    agent=gateway._registry().create_agent('owned-content',role='specialist')
    other=gateway._registry().create_agent('owned-other',role='specialist')
    gateway.store.ensure_session('owned',metadata={'agent_id':agent.id})
    gateway.store.append_message('owned','user','x'*9000+'UNICODE Straße')
    before=gateway.store.get_session('owned')
    async with TestClient(TestServer(gateway.app),headers=client_headers('webui')) as http:
        page=await (await http.get('/v1/agents/'+agent.id+'/messages/search?q=STRASSE')).json()
        hit=page['matches'][0]
        url='/v1/agents/'+agent.id+'/messages/'+hit['message_id']
        response=await http.get(url,params={'offset':hit['match_offset'],'revision':hit['content_revision']})
        assert response.status==200
        chunk=await response.json();assert chunk['content']=='Straße' and chunk['message_id']==hit['message_id']
        assert (await http.get('/v1/agents/'+other.id+'/messages/'+hit['message_id'])).status==404
        assert (await http.get(url,params={'revision':'stale'})).status==409
        assert (await http.get(url,headers=client_headers('a2a'))).status==403
        assert (await http.get('/v1/agents/missing/messages/'+hit['message_id'])).status==404
        assert gateway.store.get_session('owned')==before and gateway.store.list_requests()==[]
