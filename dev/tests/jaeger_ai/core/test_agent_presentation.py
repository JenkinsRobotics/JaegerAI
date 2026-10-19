"""Presentation persistence/contract checks; no listener, token, or live instance."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from jaeger_ai.core.gateway.agent_presentation import validate_patch, project, PresentationConflict
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.caller_auth import required_scope, prefixed_route_allowed, CALLERS


def row(aid='agent:builder', role='specialist'):
    return {'id': aid, 'kind': 'jaeger_native', 'name': 'builder', 'display_name': 'Builder', 'role': role,
            'allowed_tools': ['read_file'], 'metadata': {'context': 'unchanged'}}


def test_presentation_survives_reload_and_restore_without_identity_or_history_changes(tmp_path):
    store = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    store.ensure_session('home', metadata={'agent_id': 'agent:builder'})
    store.append_message('home', 'user', 'Keep this context')
    store.update_status('home', 'running')
    history = store.get_session('home')
    original = row()
    store.patch_agent_presentation(original['id'], {'display_name': '  New label  ', 'archived': True, 'pinned': True})
    new_store = GatewaySessionStore(store.path)
    value = project(original, new_store.agent_presentation())
    assert value['display_name'] == 'New label' and value['archived'] and value['hidden'] and value['pinned']
    for field in ('id', 'name', 'role', 'allowed_tools', 'metadata'):
        assert value[field] == original[field]
    new_store.patch_agent_presentation(original['id'], {'archived': False, 'display_name': None})
    restored = project(original, store.agent_presentation())
    assert restored['display_name'] == 'Builder' and not restored['archived'] and restored['pinned']
    assert store.get_session('home') == history
    assert original == row()


@pytest.mark.parametrize('body', [{}, [], {'role': 'lead'}, {'permissions': []}, {'owner': 'someone'}, {'display_name': ''}, {'display_name': 9}, {'display_name': 'a\nb'}, {'display_name': 'x' * 81}, {'archived': 'true'}, {'pinned': 1}])
def test_validation_rejects_execution_identity_and_invalid_values(body):
    with pytest.raises(ValueError):
        validate_patch(body)


def test_ordered_pins_merge_metadata_and_reject_stale_cross_device_write(tmp_path):
    first = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    second = GatewaySessionStore(first.path)
    first.patch_agent_presentation('a', {'display_name': 'Alias', 'archived': True})
    first.set_agent_pins(['a', 'b'], [])
    second.set_agent_pins(['b', 'a'], ['a', 'b'])
    with pytest.raises(PresentationConflict):
        first.set_agent_pins(['a'], ['a', 'b'])
    prefs = first.agent_presentation()
    assert prefs['a']['display_name'] == 'Alias' and prefs['a']['archived']
    assert prefs['b']['pin_order'] == 0 and prefs['a']['pin_order'] == 1
    second.set_agent_pins([], ['b', 'a'])
    assert not first.agent_presentation()['a']['pinned']


def test_handler_protects_lead_and_only_uses_existing_admin_scope(tmp_path):
    store = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    records = {r['id']: SimpleNamespace(id=r['id'], to_dict=lambda r=r: dict(r)) for r in [row(), row('native:jaeger', 'lead')]}
    app = SimpleNamespace(store=store, _registry=lambda: SimpleNamespace(get_agent=records.get),
                          event_bus=SimpleNamespace(publish=lambda *args: None),
                          _with_skills=lambda r: project(r, store.agent_presentation()))
    async def request(aid, body):
        async def read_json(): return body
        req = SimpleNamespace(match_info={'id': aid}, json=read_json)
        return await JaegerGatewayApp.handle_agent_presentation(app, req)
    assert asyncio.run(request('native:jaeger', {'archived': True})).status == 409
    assert asyncio.run(request('native:jaeger', {'pinned': True})).status == 409
    assert asyncio.run(request('native:jaeger', {'display_name': 'My assistant'})).status == 200
    assert records['native:jaeger'].to_dict()['display_name'] == 'Builder'
    assert asyncio.run(request('agent:builder', {'archived': True})).status == 200
    assert asyncio.run(request('agent:builder', {'archived': False})).status == 200
    assert asyncio.run(request('missing', {'display_name': 'No'})).status == 404
    assert asyncio.run(request('agent:builder', {'allowed_tools': ['shell']})).status == 400
    for method, route in [('PATCH', '/v1/agents/{id}'), ('POST', '/v1/agents/pins')]:
        assert required_scope(method, route) == 'admin'
        assert not prefixed_route_allowed(method, route)
    assert 'admin' in CALLERS['webui'].scopes and 'admin' not in CALLERS['mcp'].scopes
    assert store.agent_presentation()['agent:builder']['archived'] is False


def test_webui_proxy_preserves_existing_profile_precondition(monkeypatch):
    import sys
    from types import ModuleType
    from urllib.parse import urlparse
    from jaeger_ai.features.webui.api import jaeger_agents
    package = ModuleType('api')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, 'api', package)
    monkeypatch.setitem(sys.modules, 'api.jaeger_sessions', SimpleNamespace(route=lambda *args: False))
    context = SimpleNamespace(check_profile=lambda handler: True)
    monkeypatch.setitem(sys.modules, 'api.native_panel_context', context)
    calls = []
    monkeypatch.setattr(jaeger_agents, '_proxy', lambda handler, method, path, body: calls.append((method, path, body)) or True)
    handler = SimpleNamespace(_json_body_bytes=b'{"display_name":"Alias"}')
    assert jaeger_agents.route(handler, urlparse('/v1/agents/agent%3Abuilder'), 'PATCH')
    assert calls == [('PATCH', '/v1/agents/agent%3Abuilder', handler._json_body_bytes)]
    calls.clear()
    context.check_profile = lambda handler: False
    assert jaeger_agents.route(handler, urlparse('/v1/agents/pins'), 'POST')
    assert calls == []


def test_ordered_pin_handler_validates_ids_and_preserves_other_clients_changes(tmp_path):
    store = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    records = {r['id']: SimpleNamespace(id=r['id'], to_dict=lambda r=r: dict(r)) for r in [row(), row('native:jaeger', 'lead')]}
    app = SimpleNamespace(store=store, _registry=lambda: SimpleNamespace(get_agent=records.get), event_bus=SimpleNamespace(publish=lambda *args: None))
    async def call(body):
        async def read_json(): return body
        return await JaegerGatewayApp.handle_agent_pins(app, SimpleNamespace(json=read_json))
    assert asyncio.run(call({'agent_ids': ['agent:builder'], 'expected_agent_ids': []})).status == 200
    assert asyncio.run(call({'agent_ids': [], 'expected_agent_ids': []})).status == 409
    assert asyncio.run(call({'agent_ids': ['missing'], 'expected_agent_ids': ['agent:builder']})).status == 404
    assert asyncio.run(call({'agent_ids': ['native:jaeger'], 'expected_agent_ids': ['agent:builder']})).status == 409
    assert asyncio.run(call({'agent_ids': [], 'expected_agent_ids': ['agent:builder'], 'owner': 'someone'})).status == 400
    assert store.agent_presentation()['agent:builder']['pinned'] is True


def test_projected_controls_follow_existing_caller_scopes_even_when_skills_fail(tmp_path):
    from jaeger_ai.core.gateway.server import _REQUEST_CALLER
    store = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    store.patch_agent_presentation('agent:builder', {'display_name': 'Alias', 'archived': True})
    def broken_skills(record): raise RuntimeError('unavailable skill inventory')
    app = SimpleNamespace(store=store, _agent_skill_cards=broken_skills)
    for caller, allowed in [('webui', True), ('cli', True), ('bridge', False), ('jaegerd', False)]:
        token = _REQUEST_CALLER.set((caller, CALLERS[caller].actor))
        try:
            value = JaegerGatewayApp._with_skills(app, row())
            assert value['display_name'] == 'Alias' and value['archived']
            assert value['ui_actions']['rename'] is allowed
            assert value['ui_actions']['hide'] is allowed
        finally:
            _REQUEST_CALLER.reset(token)
