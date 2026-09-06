"""Legacy fallbacks must not bypass native-route authentication or invent Stop."""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from jaeger_ai.interfaces.hermes_profile_adapters import jaeger, openclaw
from jaeger_ai.interfaces.hermes_profile_adapters.ingress import ProfileHTTPServer


@contextmanager
def server_for(module, monkeypatch):
    monkeypatch.setenv('JAEGERS_ADAPTER_NATIVE_RUNS', 'false')
    monkeypatch.setenv('OPENCLAW_ADAPTER_NATIVE_RUNS', 'false')
    monkeypatch.setattr(module, 'profile_key', lambda _: 'test-credential')
    base = jaeger.RunHandler if module is jaeger else openclaw.Handler
    calls = []
    class Handler(base):
        def accepted(self, *args):
            calls.append(self.path)
            self.native_json(200, {'private': 'native response'})
        _handle_chat_completions = accepted
        create_chat_completion = accepted
        _handle_create_run = accepted
        create_run = accepted
        _handle_get_events = accepted
        send_events = accepted
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    def request(path, *, method='POST', headers=None, body=None):
        req = Request(f'http://127.0.0.1:{server.server_port}' + path,
            method=method, data=None if method == 'GET' else json.dumps({} if body is None else body).encode(),
            headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)
    try:
        yield request, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize('module', [jaeger, openclaw])
@pytest.mark.parametrize('method,path', [
    ('POST', '/v1/chat/completions'), ('POST', '/v1/runs'),
    ('GET', '/v1/runs/example/events'), ('POST', '/v1/runs/example/cancel'),
])
@pytest.mark.parametrize('headers,status', [
    ({}, 401), ({'Authorization': 'Bearer wrong'}, 401),
    ({'Authorization': 'Bearer test-credential', 'Origin': 'https://untrusted.invalid'}, 403),
])
def test_legacy_routes_enforce_credentials_and_origin(module, method, path, headers, status, monkeypatch):
    with server_for(module, monkeypatch) as (request, calls):
        actual, _ = request(path, method=method, headers=headers)
        assert actual == status
        assert not calls


@pytest.mark.parametrize('module', [jaeger, openclaw])
def test_legacy_cancel_does_not_invent_native_abort(module, monkeypatch):
    run_id = 'security-test-run'
    module._runs[run_id] = {'status': 'running'}
    try:
        with server_for(module, monkeypatch) as (request, _):
            status, data = request(f'/v1/runs/{run_id}/cancel',
                                  headers={'Authorization': 'Bearer test-credential'})
        assert status == 501
        assert data['error_category'] == 'unsupported_control'
        assert module._runs[run_id]['status'] == 'running'
    finally:
        module._runs.pop(run_id, None)


@pytest.mark.parametrize('module', [jaeger, openclaw])
@pytest.mark.parametrize('headers,body', [
    ({'Content-Length': '1000001'}, {}),
    ({'Transfer-Encoding': 'chunked'}, {}),
    ({'Content-Type': 'text/plain'}, {}),
    ({}, ['not', 'an', 'object']),
])
def test_legacy_rejects_invalid_body_before_dispatch(module, headers, body, monkeypatch):
    with server_for(module, monkeypatch) as (request, calls):
        status, _ = request('/v1/chat/completions', body=body,
            headers={'Authorization': 'Bearer test-credential', **headers})
        assert status == 400
        assert not calls


@pytest.mark.parametrize('module', [jaeger, openclaw])
def test_authorized_legacy_chat_still_dispatches(module, monkeypatch):
    with server_for(module, monkeypatch) as (request, calls):
        status, _ = request('/v1/chat/completions',
                           headers={'Authorization': 'Bearer test-credential'})
        assert status == 200
        assert calls == ['/v1/chat/completions']


def test_connection_capacity_is_bounded_and_recovers_after_disconnect():
    import socket
    from http.server import BaseHTTPRequestHandler
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
    server = ProfileHTTPServer(('127.0.0.1', 0), Handler, max_connections=1)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    # Hold the slot explicitly: verifies rejection without constructing a
    # request handler or parsing attacker-controlled input.
    assert server._connections.acquire(blocking=False)
    try:
        with socket.create_connection(server.server_address, timeout=2) as connection:
            response = connection.recv(4096)
            assert b'503 Service Unavailable' in response
            assert b'adapter_capacity' in response
        server._connections.release()
        with socket.create_connection(server.server_address, timeout=2) as connection:
            connection.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
            assert b'501 Unsupported method' in connection.recv(4096)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_roundtable_sends_the_selected_members_gateway_credential(monkeypatch):
    from jaeger_ai.interfaces.hermes_profile_adapters import roundtable, native_runs
    import io
    captured = []
    monkeypatch.setattr(native_runs, 'profile_key', lambda profile: 'test-' + profile)
    def request(req, **kwargs):
        captured.append(req)
        return io.BytesIO(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
    monkeypatch.setattr(roundtable.urllib.request, 'urlopen', request)
    assert roundtable.chat_openclaw('hello', 'existing-session') == 'ok'
    assert captured[0].get_header('Authorization') == 'Bearer test-openclaw'
    assert captured[0].get_header('X-hermes-session-id') == 'existing-session'
