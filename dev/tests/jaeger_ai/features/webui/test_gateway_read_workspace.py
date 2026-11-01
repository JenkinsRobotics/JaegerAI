import importlib.util
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from jaeger_ai.contract.ports import resolve_gateway_url

SRC = Path(__file__).resolve().parents[5]
FILE = SRC / 'jaeger_ai/features/webui/api/gateway_read_workspace.py'
source = FILE.read_text()

class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): self.close()

@pytest.fixture
def resolver(tmp_path):
    pkg = 'jaeger_ai.features.webui.api'
    module = types.ModuleType(pkg + '.gateway_read_workspace')
    module.__package__ = pkg
    exec(compile(source, str(FILE), 'exec'), module.__dict__)
    gateway = types.ModuleType(pkg + '.jaeger_agents')
    gateway.gateway_base = resolve_gateway_url
    profiles = types.ModuleType(pkg + '.profiles')
    profiles._profiles_match = lambda row, active: row == active
    profiles.get_active_profile_name = lambda: 'default'
    workspace = types.ModuleType(pkg + '.workspace')
    workspace.resolve_trusted_workspace = lambda value: Path(value).resolve(strict=True)
    auth = types.ModuleType('jaeger_ai.core.gateway.caller_auth')
    auth.client_headers = lambda caller: {'Authorization': 'test'}
    with patch.dict(sys.modules, {gateway.__name__: gateway, profiles.__name__: profiles,
                                  workspace.__name__: workspace, auth.__name__: auth}):
        yield module.gateway_read_workspace, tmp_path, module

def test_gateway_session_workspace(resolver):
    resolve, root, module = resolver
    row = {'session_id': 'gateway-1', 'profile': 'default', 'workspace': str(root)}
    with patch.object(module, 'urlopen', return_value=Response(json.dumps(row).encode())) as call:
        assert resolve('gateway-1') == root.resolve()
        assert call.call_args.args[0].full_url.endswith('/v1/sessions/gateway-1')
        assert call.call_args.args[0].get_header('Authorization') == 'test'

def test_unknown_or_foreign_rejected(resolver):
    resolve, root, module = resolver
    for row in ({'error': 'Session not found'},
                {'session_id': 'other', 'profile': 'default', 'workspace': str(root)},
                {'session_id': 'gateway-1', 'profile': 'foreign', 'workspace': str(root)},
                {'session_id': 'gateway-1', 'profile': 'default', 'workspace': ''}):
        with patch.object(module, 'urlopen', return_value=Response(json.dumps(row).encode())):
            with pytest.raises(KeyError): resolve('gateway-1')

def test_missing_workspace_rejected(resolver):
    resolve, root, module = resolver
    row = {'session_id': 'gateway-1', 'profile': 'default', 'workspace': str(root / 'missing')}
    with patch.object(module, 'urlopen', return_value=Response(json.dumps(row).encode())):
        with pytest.raises(KeyError): resolve('gateway-1')

def test_legacy_git_session_keeps_webui_workspace(tmp_path):
    import ast
    import runpy
    text = (SRC / 'jaeger_ai/features/webui/api/route_git.py').read_text()
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)
                and n.name == '_git_session_workspace')
    called = []
    namespace = {'Path': Path, 'Any': object, '_get_session': lambda sid: types.SimpleNamespace(workspace=str(tmp_path)),
                 'bad': lambda *args: called.append(args)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations', asname=None)], level=0), node], type_ignores=[])), '<proposed route>', 'exec'), namespace)
    assert namespace['_git_session_workspace'](object(), 'webui-1') == tmp_path
    assert not called


def test_read_path_escapes_rejected(tmp_path):
    import ast
    helper_text = (SRC / 'jaeger_ai/features/webui/api/helpers.py').read_text()
    node = next(n for n in ast.parse(helper_text).body if isinstance(n, ast.FunctionDef)
                and n.name == 'safe_resolve')
    namespace = {'Path': Path}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<source helper>', 'exec'), namespace)
    safe_resolve = namespace['safe_resolve']
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside')
    (workspace / 'link').symlink_to(outside)
    with pytest.raises(ValueError): safe_resolve(workspace, '../outside.txt')
    with pytest.raises(ValueError): safe_resolve(workspace, 'link')
