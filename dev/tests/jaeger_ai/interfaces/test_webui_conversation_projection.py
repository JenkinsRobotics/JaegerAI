import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


@pytest.fixture
def projection(monkeypatch):
    path = Path(__file__).resolve().parents[4] / 'integrations/hermes_webui/jaeger_conversation.py'
    spec = importlib.util.spec_from_file_location('jaeger_conversation_projection_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profiles = ModuleType('api.profiles')
    profiles.get_active_profile_name = lambda: 'jaeger'
    monkeypatch.setitem(sys.modules, 'api.profiles', profiles)
    return module, profiles


def test_other_profiles_do_not_query_jaeger_or_change_history(projection):
    module, profiles = projection
    profiles.get_active_profile_name = lambda: 'openclaw'
    def forbidden():
        raise AssertionError('Cross-profile native request')
    module.native = forbidden
    raw = {'messages': [{'role': 'assistant', 'content': 'OpenClaw'}]}
    assert module.project_session(raw, 'sid', True, None, None) is raw


def test_dispatcher_projection_preserves_identity_and_paginates_native_history(projection):
    module, _ = projection
    module.native = lambda: {'dispatcher_session': 'primary', 'revision': '13', 'messages': [
        {'id': str(i), 'role': 'assistant', 'text': f'message {i}', 'ts': i} for i in range(10, 14)]}
    raw = {'session_id': 'primary', 'messages': [{'content': 'stale browser copy'}], 'model': 'selected'}
    value = module.project_session(raw, 'primary', True, 2, 3)
    assert [m['id'] for m in value['messages']] == ['jaeger-11', 'jaeger-12']
    assert value['_messages_offset'] == 1 and value['_messages_truncated']
    assert value['message_count'] == 4 and value['model'] == 'selected'
    assert module.project_session(raw, 'focus', True, 2, 3) is raw
    assert module.project_session(raw, 'primary', False, None, None)['messages'] == []


def test_disconnect_preserves_cached_history_with_explicit_sync_error(projection):
    module, _ = projection
    def unavailable():
        raise OSError('connection lost')
    module.native = unavailable
    raw = {'messages': [{'content': 'keep this message'}]}
    value = module.project_session(raw, 'primary', True, None, None)
    assert value['messages'] == raw['messages']
    assert value['jaeger_sync_error']
