"""The embedded terminal attaches to the authenticated Gateway session without shadow rows."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch
from jaeger_ai.features.webui.api import gateway_read_workspace

@pytest.fixture
def terminal_route():
    # Load the actual route with the same package boundaries as the WebUI host,
    # replacing only unrelated heavyweight config and transport dependencies.
    package = 'jaeger_ai.features.webui.api'
    imports = {}
    for name in ('config', 'helpers', 'sse_chunked', 'streaming', 'workspace'):
        imports[package + '.' + name] = types.ModuleType(package + '.' + name)
    imports[package + '.config'].get_config = lambda: {}
    for name in ('bad', 'j', 'require', '_sanitize_error'):
        setattr(imports[package + '.helpers'], name, Mock())
    imports[package + '.sse_chunked'].end_sse_headers = Mock()
    imports[package + '.streaming']._sse = Mock()
    imports[package + '.streaming']._sse_set_write_deadline = Mock()
    imports[package + '.workspace']._is_remote_terminal_backend = lambda cfg: False
    imports[package + '.workspace'].resolve_trusted_workspace = lambda value: Path(value)
    path = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api/route_terminal.py'
    spec = importlib.util.spec_from_file_location(package + '.route_terminal', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, imports):
        spec.loader.exec_module(module)
        yield module


def test_gateway_workspace_lookup_is_profile_scoped_and_does_not_create_session(monkeypatch, tmp_path, terminal_route):
    monkeypatch.setattr(terminal_route, '_get_session', Mock(side_effect=KeyError('missing')))
    resolve = Mock(return_value=tmp_path)
    monkeypatch.setattr(gateway_read_workspace, 'gateway_read_workspace', resolve)
    sid, session = terminal_route._terminal_session_lookup({'session_id': 'gateway-selected'})
    assert sid == 'gateway-selected'
    assert session.workspace == str(tmp_path)
    resolve.assert_called_once_with('gateway-selected')


def test_unknown_or_foreign_gateway_session_is_rejected(monkeypatch, terminal_route):
    monkeypatch.setattr(terminal_route, '_get_session', Mock(side_effect=KeyError('missing')))
    monkeypatch.setattr(gateway_read_workspace, 'gateway_read_workspace', Mock(side_effect=KeyError('foreign')))
    with pytest.raises(KeyError, match='Session not found'):
        terminal_route._terminal_session_lookup({'session_id': 'foreign'})


def test_terminal_gate_precedes_every_session_lookup(monkeypatch, terminal_route):
    lookup = Mock(side_effect=AssertionError('must not look up session'))
    monkeypatch.setattr(terminal_route, '_terminal_session_lookup', lookup)
    monkeypatch.setattr(terminal_route, '_embedded_terminal_gate_allows', lambda handler: False)
    reject = Mock(return_value=True)
    monkeypatch.setattr(terminal_route, 'bad', reject)
    assert terminal_route.handle_terminal_start(object(), {'session_id': 'selected'})
    lookup.assert_not_called()
    assert reject.call_args.args[2] == 403


def test_legacy_session_preserves_its_existing_workspace(monkeypatch, terminal_route):
    row = SimpleNamespace(workspace='/legacy')
    monkeypatch.setattr(terminal_route, '_get_session', lambda sid: row)
    resolve = Mock(side_effect=AssertionError('not a Gateway session'))
    monkeypatch.setattr(gateway_read_workspace, 'gateway_read_workspace', resolve)
    assert terminal_route._terminal_session_lookup({'session_id': 'legacy'}) == ('legacy', row)
    resolve.assert_not_called()

@pytest.mark.parametrize('action', ['input', 'resize', 'close'])
def test_gateway_terminal_rechecks_current_session_scope(monkeypatch, terminal_route, action):
    # A terminal opened under profile A must not be writable after profile switch
    # to B, even when its opaque session id is known. No real PTY is started.
    monkeypatch.setattr(terminal_route, '_embedded_terminal_gate_allows', lambda handler: True)
    monkeypatch.setattr(terminal_route, '_terminal_session_lookup', Mock(side_effect=KeyError('Session not found')))
    backend = types.ModuleType('jaeger_ai.features.webui.api.terminal')
    methods = {'input':'write_terminal','resize':'resize_terminal','close':'close_terminal'}
    operation = Mock()
    setattr(backend, methods[action], operation)
    with patch.dict(sys.modules, {'jaeger_ai.features.webui.api.terminal':backend, 'api.terminal':backend}):
        getattr(terminal_route, 'handle_terminal_' + action)(object(), {'session_id':'profile-A-gateway-session','data':'echo scope','rows':24,'cols':80})
    operation.assert_not_called()


def test_gateway_terminal_preserves_exact_opaque_id(monkeypatch, tmp_path, terminal_route):
    monkeypatch.setattr(terminal_route, '_get_session', Mock(side_effect=KeyError('missing')))
    resolve = Mock(return_value=tmp_path)
    monkeypatch.setattr(gateway_read_workspace, 'gateway_read_workspace', resolve)
    opaque_id = ' historic / α '
    sid, _ = terminal_route._terminal_session_lookup({'session_id':opaque_id})
    assert sid == opaque_id
    resolve.assert_called_once_with(opaque_id)

@pytest.mark.parametrize('action', ['input', 'resize', 'close'])
def test_terminal_existing_scope_preserves_exact_id(monkeypatch, terminal_route, action):
    sid = ' historic / α '
    monkeypatch.setattr(terminal_route, '_embedded_terminal_gate_allows', lambda handler: True)
    monkeypatch.setattr(terminal_route, '_terminal_session_lookup', Mock(return_value=(sid, SimpleNamespace(workspace='/legacy'))))
    backend = types.ModuleType('jaeger_ai.features.webui.api.terminal')
    operation = Mock()
    setattr(backend, {'input': 'write_terminal', 'resize': 'resize_terminal', 'close': 'close_terminal'}[action], operation)
    with patch.dict(sys.modules, {'jaeger_ai.features.webui.api.terminal': backend, 'api.terminal': backend}):
        getattr(terminal_route, 'handle_terminal_' + action)(object(), {'session_id': sid, 'data': 'echo scope'})
    assert operation.call_args.args[0] == sid


def test_terminal_output_rejects_scope_before_attachment(monkeypatch, terminal_route):
    monkeypatch.setattr(terminal_route, '_embedded_terminal_gate_allows', lambda handler: True)
    monkeypatch.setattr(terminal_route, '_terminal_session_lookup', Mock(side_effect=KeyError('Session not found')))
    backend = types.ModuleType('jaeger_ai.features.webui.api.terminal')
    backend.attach_terminal = Mock()
    with patch.dict(sys.modules, {'jaeger_ai.features.webui.api.terminal': backend, 'api.terminal': backend}):
        terminal_route.handle_terminal_output(Mock(), SimpleNamespace(query='session_id=foreign'))
    backend.attach_terminal.assert_not_called()
    assert terminal_route.bad.call_args.args[2] == 404


@pytest.mark.parametrize('buffered', [True, False])
def test_terminal_output_revocation_withholds_buffer_and_unsubscribes(monkeypatch, terminal_route, buffered):
    import queue
    from urllib.parse import urlencode
    sid = ' historic / α '
    monkeypatch.setattr(terminal_route, '_embedded_terminal_gate_allows', lambda handler: True)
    lookup = Mock(side_effect=[(sid, SimpleNamespace(workspace='/work')), KeyError('Session not found')])
    monkeypatch.setattr(terminal_route, '_terminal_session_lookup', lookup)
    output = Mock()
    if buffered:
        output.get.return_value = (7, 'output', {'text': 'private buffered output'})
    else:
        output.get.side_effect = queue.Empty
    term = Mock()
    backend = types.ModuleType('jaeger_ai.features.webui.api.terminal')
    backend.attach_terminal = Mock(return_value=(term, output))
    handler = Mock(headers={})
    with patch.dict(sys.modules, {'jaeger_ai.features.webui.api.terminal': backend, 'api.terminal': backend}):
        assert terminal_route.handle_terminal_output(handler, SimpleNamespace(query=urlencode({'session_id': sid})))
    backend.attach_terminal.assert_called_once_with(sid, after_seq=None)
    assert all(call.args == ({'session_id': sid},) for call in lookup.call_args_list)
    terminal_route._sse.assert_called_once_with(handler, 'terminal_error', {'error': 'Terminal session is no longer available.'})
    handler.wfile.write.assert_not_called()
    term.unsubscribe.assert_called_once_with(output)
