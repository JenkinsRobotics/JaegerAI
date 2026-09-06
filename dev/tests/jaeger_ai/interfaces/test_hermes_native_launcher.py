from pathlib import Path
import runpy

import pytest


@pytest.fixture
def options():
    path = Path(__file__).resolve().parents[4] / 'scripts/run-hermes-native-api.py'
    return runpy.run_path(str(path))['api_options']


def test_native_launcher_requires_private_key(tmp_path, options):
    path = tmp_path / 'key'
    path.write_text('a' * 48)
    path.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        options(path, '127.0.0.1', 8645)
    path.chmod(0o600)
    config = options(path, '127.0.0.1', 8645)
    assert config == {'key': 'a'*48, 'host': '127.0.0.1', 'port': 8645, 'cors_origins': []}


def test_native_launcher_rejects_unsafe_settings(tmp_path, options):
    path = tmp_path / 'key'
    path.write_text('short')
    path.chmod(0o600)
    with pytest.raises(ValueError, match='short'):
        options(path, '127.0.0.1', 8645)
    with pytest.raises(ValueError, match='port'):
        options(path, '127.0.0.1', 80)
    with pytest.raises(ValueError, match='container'):
        options(path, 'example.com', 8645)


def test_provision_is_private_and_does_not_rotate_existing_key(tmp_path):
    module = runpy.run_path(str(Path(__file__).resolve().parents[4] / 'scripts/run-hermes-native-api.py'))
    path = tmp_path / 'credentials/key'
    module['provision_key'](path)
    original = path.read_bytes()
    assert len(original) > 32
    assert path.stat().st_mode & 0o777 == 0o600
    module['provision_key'](path)
    assert path.read_bytes() == original


def test_runs_restore_native_history_without_flattening_or_cross_session_fallback():
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[4] / 'integrations/hermes_webui/jaeger_hermes_runs.py'
    resumable = runpy.run_path(str(path))['resumable_adapter']
    history = [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'native-call'}]},
               {'role': 'tool', 'content': 'result', 'tool_call_id': 'native-call'}]
    seen = []
    class DB:
        def resolve_resume_session_id(self, sid): return 'child' if sid == 'parent' else sid
        def get_messages_as_conversation(self, sid):
            seen.append(sid)
            if sid == 'broken': raise OSError('DB unavailable')
            return history if sid == 'child' else []
    class Base:
        def _ensure_session_db(self): return DB()
        def _create_agent(self, **kwargs):
            return SimpleNamespace(session_id=kwargs['session_id'], run_conversation=lambda **kw: kw)
    adapter = resumable(Base)()
    agent = adapter._create_agent(session_id='parent')
    assert agent.session_id == 'child'
    assert agent.run_conversation(user_message='next', conversation_history=[])['conversation_history'] == history
    assert adapter._create_agent(session_id='other').run_conversation(user_message='new')['conversation_history'] == []
    with pytest.raises(OSError):
        adapter._create_agent(session_id='broken').run_conversation(user_message='next')
    assert seen == ['child', 'other', 'broken']
    assert agent.run_conversation(conversation_history=[{'role': 'user', 'content': 'explicit'}])['conversation_history'][0]['content'] == 'explicit'


def test_service_definition_uses_repo_code_and_no_embedded_credentials():
    root = Path(__file__).resolve().parents[4]
    module = runpy.run_path(str(root/'scripts/setup-hermes-native-api.py'))
    config = module['configuration']()
    assert config['ProgramArguments'] == [str(root/'.venv/bin/python'), str(root/'scripts/hermes-native-api-service.py')]
    assert config['KeepAlive'] is True and config['ThrottleInterval'] >= 20
    assert 'EnvironmentVariables' not in config
    assert str(root/'.jaeger_ai/shared/logs') in config['StandardErrorPath']


def test_service_shim_discovers_active_container_without_starting_legacy_one(monkeypatch):
    from jaeger_ai.core.runtime import agent_workspaces
    monkeypatch.setattr(agent_workspaces, 'container_name', lambda role: 'jaeger-hermes-webui' if role == 'hermes' else None)
    root = Path(__file__).resolve().parents[4]
    args = runpy.run_path(str(root/'scripts/hermes-native-api-service.py'))['command']()
    assert args[:5] == ['/opt/homebrew/bin/container', 'exec', '--user', 'hermeswebui', 'jaeger-hermes-webui']
    assert 'start' not in args and '--token' not in args


def test_roundtable_native_api_resumes_existing_named_cli_lineage():
    from types import SimpleNamespace
    import uuid
    member = 'a' * 32
    legacy = uuid.uuid5(uuid.NAMESPACE_URL, f'jaeger-roundtable:{member}:hermes').hex
    calls = []
    class DB:
        def resolve_session_by_title(self, title):
            calls.append(title)
            return 'original-cli-session'
        def resolve_resume_session_id(self, sid):
            assert sid == 'original-cli-session'
            return 'compressed-child'
        def get_messages_as_conversation(self, sid):
            assert sid == 'compressed-child'
            return [{'role': 'user', 'content': 'old context'}]
    class Base:
        def _ensure_session_db(self): return DB()
        def _create_agent(self, **kwargs):
            return SimpleNamespace(session_id=kwargs['session_id'], run_conversation=lambda **kw: kw)
    path = Path(__file__).resolve().parents[4] / 'integrations/hermes_webui/jaeger_hermes_runs.py'
    agent = runpy.run_path(str(path))['resumable_adapter'](Base)()._create_agent(session_id=f'roundtable-hermes:{member}')
    assert agent.session_id == 'compressed-child'
    assert calls == [f'Roundtable {legacy[:12]} — Hermes']
    assert agent.run_conversation()['conversation_history'][0]['content'] == 'old context'
