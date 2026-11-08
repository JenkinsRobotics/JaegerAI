"""Approval details preserve the complete redacted request; no shell execution."""
import asyncio
from types import SimpleNamespace

from jaeger_ai.core.gateway.server import _approval_target, _GatewayToolConfirmationProvider
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


def request(tail='SECOND_ACTION'):
    return SimpleNamespace(skill='terminal', operation='run_terminal', summary='synthetic request',
        tier=SimpleNamespace(name='PRIVILEGED'), arguments={
            'command': "printf '%s' '" + 'x' * 240 + "'; printf '%s' '" + tail + "'",
            'cwd': '/synthetic/other-directory', 'env': {'API_KEY': 'fixture-secret'},
            'timeout': 12, 'empty': '', 'disabled': False,
            'author': 'Synthetic Author', 'max_tokens': 321, 'recipient': 'fixture-recipient',
        })


def test_complete_arguments_distinguish_suffix_and_redact_without_mutation():
    first, second = request(), request('DIFFERENT_ACTION')
    shown = _approval_target(first)
    assert shown != _approval_target(second)
    assert 'SECOND_ACTION' in shown and '/synthetic/other-directory' in shown
    assert 'timeout' in shown and '12' in shown and 'disabled' in shown
    assert 'fixture-secret' not in shown and '[REDACTED]' in shown
    assert first.arguments['env']['API_KEY'] == 'fixture-secret'
    assert 'Synthetic Author' in shown and '321' in shown and 'fixture-recipient' in shown


def test_broker_persists_and_publishes_full_redacted_action(tmp_path):
    async def run():
        store = GatewaySessionStore(tmp_path / 'approvals.sqlite3')
        published = []
        app = SimpleNamespace(_loop=asyncio.get_running_loop(), pending_approvals={},
            store=store, _cancellations={}, _approval_origin=lambda session: None)
        def publish(session, origin, payload):
            published.append(payload)
            aid = payload['approval_id']
            store.resolve_approval(aid, approved=False, decision='deny')
            app.pending_approvals[aid].set_result(False)
        app._publish_approval_request = publish
        broker = _GatewayToolConfirmationProvider(app, 'visibility-session', 'visibility-request')
        assert not await asyncio.to_thread(broker._prompt, request())
        row = store.get_approval(published[0]['approval_id'])
        for text in (row['prompt'], row['metadata']['target'], published[0]['prompt'], published[0]['target']):
            assert 'SECOND_ACTION' in text and '/synthetic/other-directory' in text
            assert 'fixture-secret' not in text
        assert row['decision'] == 'deny'
    asyncio.run(run())


def test_large_multiline_and_quoted_secret_details_are_not_clipped():
    req = request()
    req.arguments['content'] = 'line\n' * 10000 + 'END_OF_LARGE_ARGUMENT'
    req.arguments['headers'] = {'Authorization': 'Bearer fixture-bearer-value'}
    req.arguments['command'] += ' PASSWORD="fixture password value"'
    shown = _approval_target(req)
    assert 'END_OF_LARGE_ARGUMENT' in shown and len(shown) > 50000
    assert 'fixture-bearer-value' not in shown and 'fixture password value' not in shown
    assert 'SECOND_ACTION' in shown


def test_structured_credentials_masked_without_hiding_ordinary_scope():
    req = request()
    req.arguments.update({'headers': {'Cookie': 'fixture-cookie'},
        'credentials': {'value': 'fixture-credential'},
        'env': {'AWS_SECRET_ACCESS_KEY': 'fixture-cloud-secret'},
        'accessToken': 'fixture-access', 'token_count': 42})
    shown = _approval_target(req)
    for secret in ('fixture-cookie', 'fixture-credential', 'fixture-cloud-secret', 'fixture-access'):
        assert secret not in shown
    assert 'Synthetic Author' in shown and '321' in shown and 'token_count=42' in shown


def test_numeric_credentials_are_not_treated_as_token_counts():
    req = request()
    req.arguments.update({'password': 981276, 'token': 912783, 'credential': 981234,
                          'token_count': 42, 'max_tokens': 321})
    shown = _approval_target(req)
    assert all(str(value) not in shown for value in (981276, 912783, 981234))
    assert 'token_count=42' in shown and 'max_tokens=321' in shown
    assert req.arguments['password'] == 981276


def test_unsupported_values_and_keys_never_invoke_stringification():
    calls = []
    class InternalContext:
        def __str__(self):
            calls.append('str')
            return 'private_internal_material=synthetic-hidden-session'
        def __repr__(self):
            calls.append('repr')
            return 'synthetic-hidden-repr'
    context = InternalContext()
    req = request()
    req.arguments['context'] = context
    req.arguments['nested'] = {'object': context}
    shown = _approval_target(req)
    assert not calls
    assert 'Unavailable' in shown and 'synthetic-hidden' not in shown
    assert 'SECOND_ACTION' in shown
    req.arguments['nested'] = {context: 'hidden-associated-value'}
    shown = _approval_target(req)
    assert not calls and 'hidden-associated-value' not in shown
    assert 'unsupported argument key' in shown
    req.arguments = context
    assert 'Unavailable' in _approval_target(req) and not calls


def test_explicit_private_key_and_space_separated_api_key_are_masked():
    req = request()
    req.arguments.update({'private_key': 'fixture-private-key', 'api key': 'fixture-space-key'})
    shown = _approval_target(req)
    assert 'fixture-private-key' not in shown and 'fixture-space-key' not in shown
    assert 'Synthetic Author' in shown and 'max_tokens=321' in shown


def test_cyclic_values_and_builtin_subclasses_have_explicit_unavailable_markers():
    class DangerousString(str):
        def __str__(self):
            raise AssertionError('must not stringify subclass')
    cycle = []
    cycle.append(cycle)
    req = request()
    req.arguments.update({'cycle': cycle, 'subclass': DangerousString('hidden-subclass'),
                          'normal': {'value': ['ordinary', 17]}})
    shown = _approval_target(req)
    assert 'cyclic argument value' in shown and 'unsupported argument value' in shown
    assert 'hidden-subclass' not in shown and 'ordinary' in shown and '17' in shown


def test_nonidentifier_argument_labels_cannot_forge_display_lines():
    import json

    ordinary = {'command': 'printf harmless', 'cwd': '/synthetic', 'max_tokens': 321}
    unusual = ['note\ncommand', 'note\rcommand', 'note\tcommand', 'note\x1b[2J',
               'note=command', 'quote"label', 'path\\label', '\u202ecommand',
               'étiquette', 'api key', '']
    for key in unusual:
        arguments = {**ordinary, key: 'fixture-value'}
        shown = _approval_target(SimpleNamespace(arguments=arguments))
        lines = shown.splitlines()
        assert len(lines) == len(arguments), (key, shown)
        assert lines[:3] == ['command="printf harmless"', 'cwd="/synthetic"', 'max_tokens=321']
        assert lines[-1].startswith(json.dumps(key, ensure_ascii=True) + '=')
        assert not any(ord(character) < 32 or ord(character) > 126 for character in lines[-1])
        assert arguments[key] == 'fixture-value'  # display never rewrites invocation input


def test_mcp_extra_argument_labels_are_escaped_without_changing_dispatch(monkeypatch):
    from jaeger_ai.plugins.mcp.client import MCPToolSpec, _register_agent_tool
    from jaeger_os.core.tools import tool_registry
    from jaeger_os.core.safety import permissions

    registered, requests, calls = [], [], []
    spec = MCPToolSpec(qualified_name='mcp:synthetic/check', server_name='synthetic',
        tool_name='check', description='Synthetic display fixture',
        input_schema={'type': 'object', 'properties': {'cwd': {'type': 'string'}},
                      'additionalProperties': False}, agent_name='synthetic_key_review')
    arguments = {'cwd': '/actual-synthetic', 'note="benign"\ncwd': '/forged-synthetic'}
    monkeypatch.setattr(tool_registry, 'has_tool', lambda name: False)
    monkeypatch.setattr(tool_registry, 'register_tool_instance', registered.append)
    monkeypatch.setattr(permissions, 'current_policy', lambda: SimpleNamespace(check=requests.append))
    monkeypatch.setattr('jaeger_ai.plugins.mcp.client.call_mcp_tool',
                        lambda name, args: calls.append((name, args)) or {'synthetic': True})
    _register_agent_tool(spec)
    registered[0].fn(**arguments)
    assert len(requests) == len(calls) == 1
    assert requests[0].arguments == arguments == calls[0][1]
    shown = _approval_target(requests[0])
    assert len(shown.splitlines()) == 2
    assert '\ncwd="/forged-synthetic"' not in shown
    assert shown.splitlines()[0] == 'cwd="/actual-synthetic"'
    assert '\\ncwd' in shown


def test_directional_and_nonprinting_argument_values_are_visibly_escaped():
    import json

    for value in ['safe\u202eevil\u202c', '/safe/\u2066hidden\u2069',
                  'zero\u200bwidth', 'invisible\u200djoin', 'line\u2028separator', 'café']:
        arguments = {'command': value, 'cwd': value, 'nested': {'value': value}}
        shown = _approval_target(SimpleNamespace(arguments=arguments))
        assert shown.splitlines() == ['command=' + json.dumps(value, ensure_ascii=True),
                                     'cwd=' + json.dumps(value, ensure_ascii=True),
                                     'nested=' + json.dumps({'value': value}, ensure_ascii=True)]
        assert not any(ord(character) > 126 for character in shown)
        assert arguments['command'] == arguments['cwd'] == arguments['nested']['value'] == value
