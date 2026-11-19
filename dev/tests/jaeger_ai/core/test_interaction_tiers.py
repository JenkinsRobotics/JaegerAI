"""Normal conversations can use tools; Plan and explicit grants still restrict them."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import make_mocked_request

from jaeger_ai.contract.modes import (
    DEFAULT_INTERACTION_TIER, INTERACTION_TIERS, TIER_DESCRIPTIONS,
    normalize_interaction_tier,
)
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.instance.schemas import AutomationConfig, Config, ModelConfig, dump_yaml, load_yaml
from jaeger_ai.core.settings.catalog import describe


def test_normal_conversation_contract():
    assert INTERACTION_TIERS == ('agent', 'plan')
    assert DEFAULT_INTERACTION_TIER == 'agent'
    assert set(TIER_DESCRIPTIONS) == set(INTERACTION_TIERS)
    for old in ('chat', 'jaeger'):
        assert normalize_interaction_tier(old) == 'agent'
        assert AutomationConfig(interaction_tier=old).interaction_tier == 'agent'
    assert AutomationConfig().autonomy == 'scoped'
    assert AutomationConfig(interaction_tier='plan').interaction_tier == 'plan'


def test_settings_catalog_exposes_only_current_styles(tmp_path):
    path = tmp_path / 'config.yaml'
    dump_yaml(path, Config(instance_name='test', model=ModelConfig(model_path='/dev/null')))
    desc = describe(SimpleNamespace(config_path=path), 'automation.interaction_tier')
    assert desc['choices'] == ['agent', 'plan']
    assert desc['current'] == desc['default'] == 'agent'


@pytest.mark.parametrize('grant', [None, [], ['read_file']])
def test_admission_migrates_chat_without_widening_explicit_tool_grants(tmp_path, grant):
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    requested = {'interaction_tier': 'chat', 'caller': 'owner:webui'}
    if grant is not None:
        requested['allowed_tools'] = grant
    admitted = store.admit_request('s', 'Inspect saved chats', request_id='r', requested=requested)
    execution = admitted['execution']
    assert execution['interaction_tier'] == 'agent'
    assert execution['allowed_tools'] == grant
    assert execution['caller'] == 'owner:webui'
    replay = store.admit_request('s', 'Inspect saved chats', request_id='r', requested=requested)
    assert replay['replayed'] and replay['execution'] == execution


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    from jaeger_ai.core.entity.runtime import EntityRuntime
    monkeypatch.setenv('JAEGER_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('JAEGER_LEGACY_PATHS', '0')
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    app = JaegerGatewayApp(store=store)
    app.app.on_startup.clear()
    runtime = SimpleNamespace(
        prepare_turn=Mock(side_effect=lambda text, **kw: SimpleNamespace(prompt=text, context_references=())),
        finish_turn=Mock(),
    )
    monkeypatch.setattr(EntityRuntime, 'get_singleton', lambda: runtime)
    monkeypatch.setattr(app, '_resolve_session_agent', lambda _: None)
    monkeypatch.setattr(app, '_one_mind_front_door', lambda *args: None)
    monkeypatch.setattr(app, '_auto_route', lambda *args: False)
    monkeypatch.setattr(app, '_system_prompt_for_agent', lambda _: 'You are Jaeger.')
    monkeypatch.setattr(app, '_collaboration_prompt', lambda: '')
    monkeypatch.setattr(app, '_open_turn_card', lambda *a, **kw: (None, kw['execution']))
    monkeypatch.setattr(app, '_schedule_summary', lambda *a: None)
    monkeypatch.setattr(app, '_maybe_queue_skill_review', lambda *a, **kw: None)
    monkeypatch.setattr(app, '_catalog_tool_names', lambda: ['read_file', 'write_file', 'terminal'])
    app._continued_owner_react = Mock(return_value={'text': 'Verified answer', 'status': 'completed'})
    app._model_chat = AsyncMock(return_value='Tools are explicitly disabled for this request.')
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize('tier,text', [('chat', 'How many saved chats are there?'), ('agent', 'Hello')])
async def test_conversation_uses_agent_loop_without_requiring_an_action_keyword(gateway, tier, text):
    request = gateway.store.admit_request('s', text, request_id='r', requested={
        'interaction_tier': tier, 'caller': 'owner:webui', 'allowed_tools': ['read_file'],
    })
    await gateway._execute_turn('s', request['turn_id'], text, request_id='r', execution=request['execution'])
    gateway._model_chat.assert_not_awaited()
    gateway._continued_owner_react.assert_called_once()
    execution = gateway._continued_owner_react.call_args.kwargs['execution']
    assert execution['caller'] == 'owner:webui'
    assert execution['allowed_tools'] == ['read_file']
    assert gateway.store.get_request('r')['status'] == 'completed'


@pytest.mark.asyncio
async def test_explicit_empty_tool_grant_still_uses_no_tools(gateway):
    text = 'Inspect files'
    request = gateway.store.admit_request('s', text, request_id='r', requested={
        'interaction_tier': 'agent', 'allowed_tools': [],
    })
    await gateway._execute_turn('s', request['turn_id'], text, request_id='r', execution=request['execution'])
    gateway._continued_owner_react.assert_not_called()
    gateway._model_chat.assert_awaited_once()
    assert gateway.store.get_request('r')['status'] == 'completed'


@pytest.mark.asyncio
async def test_plan_still_narrows_the_grant_to_read_only(gateway):
    text = 'Plan a file edit'
    request = gateway.store.admit_request('s', text, request_id='r', requested={
        'interaction_tier': 'plan', 'allowed_tools': ['read_file', 'write_file', 'terminal'],
    })
    await gateway._execute_turn('s', request['turn_id'], text, request_id='r', execution=request['execution'])
    gateway._model_chat.assert_not_awaited()
    execution = gateway._continued_owner_react.call_args.kwargs['execution']
    assert execution['interaction_tier'] == 'plan'
    assert execution['allowed_tools'] == ['read_file']
    assert request['execution']['allowed_tools'] == ['read_file', 'terminal', 'write_file']


@pytest.mark.asyncio
async def test_plan_cannot_start_background_execution(gateway):
    gateway._current_tier = lambda: 'plan'
    request = make_mocked_request('POST', '/v1/tasks')
    assert (await gateway.handle_tasks(request)).status == 403
    assert (await gateway.handle_create_orchestration_task(request)).status == 403


@pytest.mark.asyncio
async def test_saved_chat_and_old_clients_migrate_without_changing_permissions(gateway, tmp_path):
    path = tmp_path / 'config.yaml'
    config = Config(instance_name='test', model=ModelConfig(model_path='/dev/null'))
    config.automation.autonomy = 'ask'
    dump_yaml(path, config)
    path.write_text(path.read_text().replace('interaction_tier: agent', 'interaction_tier: chat'))
    gateway._config_path = lambda: path
    response = await gateway.handle_get_tier(make_mocked_request('GET', '/v1/runtime/tier'))
    assert json.loads(response.body)['options'] == ['agent', 'plan']
    assert 'interaction_tier: agent' in path.read_text()
    assert load_yaml(path, Config).automation.autonomy == 'ask'
    request = make_mocked_request('POST', '/v1/runtime/tier')
    request.json = AsyncMock(return_value={'tier': 'chat'})
    response = await gateway.handle_set_tier(request)
    assert json.loads(response.body)['tier'] == 'agent'
    assert load_yaml(path, Config).automation.autonomy == 'ask'
    request.json = AsyncMock(return_value={'tier': 'unknown'})
    assert (await gateway.handle_set_tier(request)).status == 400
