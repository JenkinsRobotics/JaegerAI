"""Settings writes must not replace unreadable provider preferences with defaults."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

API = Path(__file__).resolve().parents[5] / 'jaeger_ai/features/webui/api'


def load(name):
    spec = importlib.util.spec_from_file_location('_preservation_' + name, API / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_STATE_HOME', str(tmp_path))
    module = load('cli_providers')
    monkeypatch.setattr(module, 'HOME', tmp_path)
    monkeypatch.setattr(module, 'detect', lambda: [{'id': 'codex', 'enabled': False}])
    return module


@pytest.mark.parametrize('original', [b'{"claude": {"enabled": false},', b'[]', b'null', b'42', b'\xff'])
def test_bad_saved_document_is_retained(cli, original):
    path = cli._state_path()
    path.parent.mkdir(parents=True)
    path.write_bytes(original)
    with pytest.raises(ValueError, match='Existing CLI provider settings could not be read'):
        cli.update('codex', {'enabled': False})
    assert path.read_bytes() == original
    assert cli._settings() == {}  # Read-only display fallback remains compatible.
    assert not path.with_suffix('.tmp').exists()


def test_read_failure_does_not_overwrite_or_expose_error(cli, monkeypatch):
    path = cli._state_path()
    path.parent.mkdir(parents=True)
    original = b'{"claude": {"enabled": false}}'
    path.write_bytes(original)
    read = Path.read_text
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError('synthetic-private-error-detail')
        return read(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', denied)
    with pytest.raises(ValueError) as exc:
        cli.update('codex', {'enabled': False})
    assert 'synthetic-private-error-detail' not in str(exc.value)
    assert path.read_bytes() == original


def test_missing_and_existing_document_remain_compatible(cli):
    cli.update('codex', {'enabled': False})
    path = cli._state_path()
    assert json.loads(path.read_text()) == {'codex': {'enabled': False}}
    saved = {'codex': {'enabled': True, 'models': ['auto'], 'note': 'retain'},
             'claude': {'enabled': False}, 'future': {'fixture': 'retain'}}
    path.write_text(json.dumps(saved))
    cli.update('codex', {'enabled': False})
    saved['codex']['enabled'] = False
    assert json.loads(path.read_text()) == saved
    before = path.read_bytes()
    with pytest.raises(KeyError):
        cli.update('unknown', {'enabled': True})
    assert path.read_bytes() == before


def test_settings_put_reports_failure_and_preserves_document(cli, monkeypatch):
    api = load('unified_api')
    monkeypatch.setattr(api, '_cli', lambda: cli)
    path = cli._state_path()
    path.parent.mkdir(parents=True)
    original = b'{"synthetic-private-document":'
    path.write_bytes(original)
    responses = []
    def respond(handler, data, **kwargs):
        responses.append((data, kwargs))
    assert api.route(None, urlparse('/v1/providers/cli/codex'), 'PUT',
                     lambda handler: {'enabled': False}, respond)
    assert len(responses) == 1
    assert responses[0][1]['status'] == 400
    assert 'synthetic-private-document' not in json.dumps(responses)
    assert path.read_bytes() == original
