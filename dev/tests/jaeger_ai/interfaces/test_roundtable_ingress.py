import json
from http.server import ThreadingHTTPServer
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.interfaces.hermes_profile_adapters import native_runs, roundtable


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(native_runs, 'profile_key', lambda profile: 'roundtable-secret')
    calls = []
    class Handler(roundtable.RoundtableHandler):
        def _handle_chat_completions(self):
            calls.append(self._request_body)
            self._send_json(200, {'ok': True})
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.parametrize('credential', ['', 'Bearer wrong'])
def test_legacy_execution_rejects_unauthenticated_callers(api, credential):
    base, calls = api
    req = Request(base + '/v1/chat/completions', data=b'{}', headers={'Authorization': credential})
    with pytest.raises(HTTPError) as error: urlopen(req, timeout=3)
    assert error.value.code == 401
    assert not calls


@pytest.mark.parametrize('body,headers', [
    (b'[]', {}), (b'not-json', {}), (b'{}', {'Content-Length': '1000001'}),
    (b'{}', {'Content-Type': 'text/plain'}),
])
def test_authenticated_body_is_bounded_and_validated(api, body, headers):
    base, calls = api
    req = Request(base + '/v1/chat/completions', data=body,
                  headers={'Authorization': 'Bearer roundtable-secret', 'Content-Type': 'application/json', **headers})
    with pytest.raises(HTTPError) as error: urlopen(req, timeout=3)
    assert error.value.code == 400
    assert not calls


def test_unknown_origin_is_rejected_even_with_credential(api):
    base, calls = api
    req = Request(base + '/v1/chat/completions', data=b'{}', headers={
        'Authorization': 'Bearer roundtable-secret', 'Origin': 'https://untrusted.example'})
    with pytest.raises(HTTPError) as error: urlopen(req, timeout=3)
    assert error.value.code == 403
    assert not calls


def test_authorized_proxy_call_and_public_health(api):
    base, calls = api
    with urlopen(base + '/health', timeout=3) as response:
        assert response.status == 200
        assert response.headers.get('Access-Control-Allow-Origin') is None
    req = Request(base + '/v1/chat/completions', data=b'{}', headers={
        'Authorization': 'Bearer roundtable-secret', 'Content-Type': 'application/json'})
    with urlopen(req, timeout=3) as response: assert json.load(response)['ok']
    assert calls == [{}]


def test_event_receipts_require_authentication(api):
    base, _ = api
    with pytest.raises(HTTPError) as error:
        urlopen(base + '/v1/runs/123/events', timeout=3)
    assert error.value.code == 401


def test_provision_roundtable_preserves_model_comments_and_existing_key(tmp_path):
    from pathlib import Path
    import runpy
    import yaml
    setup = runpy.run_path(str(Path(__file__).resolve().parents[4] / 'scripts/setup-native-runs.py'))
    config = tmp_path / '.hermes/profiles/roundtable/config.yaml'
    config.parent.mkdir(parents=True)
    original = '# Keep my settings\nmodel:\n  provider: ollama\n  default: glm-5.3-flash:cloud\n'
    config.write_text(original)
    setup['configure'](tmp_path, profiles=['roundtable'])
    first = config.read_text()
    assert first.startswith(original)
    assert len(yaml.safe_load(first)['webui_gateway_api_key']) >= 32
    assert config.stat().st_mode & 0o777 == 0o600
    setup['configure'](tmp_path, profiles=['roundtable'])
    assert config.read_text() == first
    assert config.with_name('config.before-native-runs.yaml').read_text() == original


@pytest.mark.parametrize('exists,code', [(True, 501), (False, 404)])
def test_legacy_cancel_never_claims_native_work_stopped(api, exists, code):
    base, _ = api
    rid = 'cancel-verification'
    if exists:
        with roundtable._runs_lock:
            roundtable._runs[rid] = {'status': 'running'}
    try:
        request = Request(base + f'/v1/runs/{rid}/cancel', data=b'{}', headers={
            'Authorization': 'Bearer roundtable-secret', 'Content-Type': 'application/json'})
        with pytest.raises(HTTPError) as error: urlopen(request, timeout=3)
        assert error.value.code == code
        if exists: assert roundtable._runs[rid]['status'] == 'running'
    finally:
        with roundtable._runs_lock: roundtable._runs.pop(rid, None)
