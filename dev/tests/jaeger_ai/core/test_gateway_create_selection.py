"""New-chat wire contract: canonical selection, authority, and safe retries."""
import copy
import json

import pytest

from jaeger_ai.core.agent_registry import AgentRegistry
from jaeger_ai.core.gateway import caller_auth
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


class Request(dict):
    can_read_body = True

    def __init__(self, body, caller='webui'):
        super().__init__(caller=caller_auth.CALLERS[caller], caller_actor=f'owner:{caller}')
        self.body = body

    async def json(self):
        return copy.deepcopy(self.body)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path))
    monkeypatch.setenv('JAEGER_HOME', str(tmp_path))
    registry = AgentRegistry(tmp_path)
    registry.create_agent('selected', scaffold_instance=False)
    registry.create_agent('other', scaffold_instance=False)
    registry.create_agent('disabled', metadata={'disabled': True}, scaffold_instance=False)
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'sessions.sqlite3'))
    monkeypatch.setattr(gateway, '_registry', lambda: registry)
    monkeypatch.setattr(gateway, '_activate_owner_session', lambda *args, **kwargs: None)
    return gateway


async def create(app, **extra):
    # GatewaySource.createSession adds these fields to homeSession's {agent_id}.
    body = {'session_id': 'new-chat', 'source': 'webui', 'title': 'New chat', **extra}
    return await app.handle_create_session(Request(body))


@pytest.mark.asyncio
@pytest.mark.parametrize('agent_id', ['selected', 'native:selected'])
async def test_ui_request_resolves_selected_agent_not_profile_default(app, agent_id):
    response = await create(app, agent_id=agent_id)
    assert response.status == 201, response.text
    row = json.loads(response.text)
    assert row['agent_id'] == 'native:selected'
    assert app._resolve_session_agent(row['session_id']).id == 'native:selected'
    assert row['metadata']['agent_pinned'] is True
    assert app._enrich_session_agent(row)['role'] == app._registry().get_agent('selected').role.value


@pytest.mark.asyncio
async def test_no_selection_keeps_legacy_default_lead_behavior(app):
    response = await create(app)
    assert response.status == 201
    assert json.loads(response.text)['agent_id'] == 'native:jaeger'
    assert app._resolve_session_agent('new-chat').id == 'native:jaeger'


@pytest.mark.asyncio
@pytest.mark.parametrize('selection,status', [('missing',404), ('disabled',403), ('',400), (42,400), (None,400)])
async def test_invalid_selection_never_creates_session(app, selection, status):
    response = await create(app, agent_id=selection)
    assert response.status == status
    assert app.store.get_session('new-chat') is None


@pytest.mark.asyncio
async def test_legacy_metadata_and_alias_agreement_are_canonical(app):
    response = await create(app, agent_id='selected', metadata={'agent_id':'native:selected', 'agent_pinned':False})
    assert response.status == 201
    assert json.loads(response.text)['metadata']['agent_pinned'] is True
    response = await create(app, session_id='legacy', metadata={'agent_id':'selected'})
    assert response.status == 201
    assert app._resolve_session_agent('legacy').id == 'native:selected'


@pytest.mark.asyncio
async def test_conflicting_selectors_rejected_without_writes(app):
    response = await create(app, agent_id='selected', metadata={'agent_id':'other'})
    assert response.status == 400
    assert app.store.get_session('new-chat') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('selection', ['selected', 'other', None])
async def test_retry_does_not_rewrite_session_or_history(app, selection):
    await create(app, agent_id='selected')
    app.store.append_message('new-chat','user','Keep this conversation')
    before = app.store.get_session('new-chat')
    extra = {'agent_id':selection} if selection else {}
    response = await create(app, title='Replacement', metadata={'model':'spoof'}, **extra)
    assert response.status == (409 if selection == 'other' else 201)
    assert app.store.get_session('new-chat') == before
    assert GatewaySessionStore(app.store.path).get_session('new-chat') == before


@pytest.mark.asyncio
@pytest.mark.parametrize('caller', ['mcp', 'a2a', 'grokbot'])
async def test_selection_cannot_bypass_agent_home_access(app, caller):
    spec = caller_auth.CALLERS[caller]
    sid = (spec.session_prefix or '') + 'new-chat'
    response = await app.handle_create_session(Request({'session_id':sid, 'agent_id':'selected'},caller))
    assert response.status == 403
    assert app.store.get_session(sid) is None


@pytest.mark.asyncio
async def test_claimed_role_kind_and_permissions_do_not_change_registry_identity(app):
    original = app._registry().get_agent('selected').to_dict()
    response = await create(app, agent_id='selected', role='lead', kind='owner', permissions=['*'],
                            metadata={'role':'lead', 'kind':'owner', 'permissions':['*']})
    assert response.status == 201
    assert app._resolve_session_agent('new-chat').to_dict() == original
    assert app._enrich_session_agent(json.loads(response.text))['role'] == original['role']


@pytest.mark.asyncio
async def test_http_ui_contract_and_authentication(app):
    from aiohttp.test_utils import TestClient, TestServer

    # Exercise production routes/middleware without starting unrelated daemon workers.
    app.app.on_startup.clear()
    app.app.on_cleanup.clear()
    async with TestClient(TestServer(app.app)) as client:
        body = {'session_id':'wire-chat', 'source':'webui', 'title':'New chat', 'agent_id':'selected'}
        unauthenticated = await client.post('/v1/sessions', json=body)
        assert unauthenticated.status == 401
        assert app.store.get_session('wire-chat') is None
        headers = caller_auth.client_headers('webui')
        response = await client.post('/v1/sessions', json=body, headers=headers)
        assert response.status == 201, await response.text()
        assert (await response.json())['agent_id'] == 'native:selected'
        detail = await client.get('/v1/sessions/wire-chat', headers=headers)
        assert (await detail.json())['agent_id'] == 'native:selected'
        listed = await client.get('/v1/sessions?agent_id=native:selected', headers=headers)
        assert [row['session_id'] for row in (await listed.json())['sessions']] == ['wire-chat']
        denied_headers = caller_auth.client_headers('mcp')
        denied = await client.post('/v1/sessions', json={**body, 'session_id':'mcp:wire'}, headers=denied_headers)
        assert denied.status == 403
        assert app.store.get_session('mcp:wire') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {'metadata': []}, {'metadata':'agent_id'}])
async def test_malformed_selection_container_rejected_without_writes(app, body):
    response = await app.handle_create_session(Request(body))
    assert response.status == 400
    assert app.store.list_sessions() == []


@pytest.mark.asyncio
async def test_legacy_metadata_retry_cannot_reassign_existing_chat(app):
    await create(app, agent_id='selected')
    app.store.append_message('new-chat', 'assistant', 'Saved answer')
    before = app.store.get_session('new-chat')
    response = await create(app, metadata={'agent_id': 'other'})
    assert response.status == 409
    assert GatewaySessionStore(app.store.path).get_session('new-chat') == before


@pytest.mark.asyncio
async def test_create_does_not_claim_historical_unassigned_session(app):
    app.store.ensure_session('historical', title='Keep title', metadata={'model': 'original'})
    app.store.append_message('historical', 'user', 'Saved history')
    before = app.store.get_session('historical')
    response = await create(app, session_id='historical', agent_id='selected')
    assert response.status == 409
    assert GatewaySessionStore(app.store.path).get_session('historical') == before


@pytest.mark.asyncio
@pytest.mark.parametrize('selection', [None, 'selected'])
async def test_null_metadata_keeps_optional_field_compatibility(app, selection):
    extra = {'agent_id': selection} if selection else {}
    response = await create(app, metadata=None, **extra)
    assert response.status == 201, response.text
    expected = 'native:selected' if selection else 'native:jaeger'
    row = json.loads(response.text)
    assert row['agent_id'] == expected
    assert app._resolve_session_agent('new-chat').id == expected
    assert isinstance(row['metadata'], dict)
