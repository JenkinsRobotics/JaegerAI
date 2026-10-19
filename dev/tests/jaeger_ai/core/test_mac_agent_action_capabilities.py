"""Source-only capability advertisement; no server/app is started."""
from types import SimpleNamespace
from pathlib import Path
from jaeger_ai.core.agent_registry.registry import with_roster_flags, _with_hidden


def test_roster_advertises_only_supported_seen_action():
    for role in ('lead', 'specialist', 'runtime'):
        identity = {'id': 'native:jaeger' if role == 'lead' else 'agent:worker', 'name': 'worker', 'role': role}
        record = SimpleNamespace(to_dict=lambda: dict(identity), name='worker', role=role, disabled=False)
        for project in (with_roster_flags, _with_hidden):
            value = project(record)
            assert value['ui_actions'] == {'read': True}
            assert all(value[k] == v for k, v in identity.items())
        assert record.to_dict() == identity


def test_supported_launcher_has_no_archived_branding_override():
    root = Path(__file__).resolve().parents[4]
    script = (root / 'scripts/run-jaeger-webui.sh').read_text()
    assert 'jaeger_webui_branding.js' not in script
    assert 'HERMES_WEBUI_EXTENSION_SCRIPT_URLS=' not in script
    serving = (root / 'jaeger_ai/features/webui/api/ui_shell.py').read_text()
    assert 'ui-rebuild-mainscreen/dist' in serving
    assert 'return "legacy"' not in serving


def test_seen_handler_is_durable_validates_input_and_preserves_history(tmp_path):
    import asyncio
    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore
    store = GatewaySessionStore(tmp_path / 'isolated-sessions.sqlite3')
    store.ensure_session('existing-home', metadata={'agent_id': 'native:jaeger'})
    store.append_message('existing-home', 'user', 'Keep my context')
    history = store.get_session('existing-home')
    app = SimpleNamespace(store=store, _registry=lambda: SimpleNamespace(get_agent=lambda aid: object() if aid == 'native:jaeger' else None))

    async def call(agent_id, body):
        async def read_json():
            return body
        request = SimpleNamespace(match_info={'id': agent_id}, can_read_body=True, json=read_json)
        return await JaegerGatewayApp.handle_agent_seen(app, request)

    assert asyncio.run(call('native:jaeger', {'seen_at': 123, 'event_id': 7})).status == 200
    assert GatewaySessionStore(store.path).agents_seen()['native:jaeger']['seen_at'] == 123
    assert asyncio.run(call('native:jaeger', {'seen_at': 'invalid'})).status == 400
    assert asyncio.run(call('missing', {})).status == 404
    assert store.agents_seen()['native:jaeger']['seen_at'] == 123
    assert store.get_session('existing-home') == history
