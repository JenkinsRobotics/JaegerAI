"""Both API namespaces return JSON denials; page paths retain login redirects."""
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
import api.auth as auth


class Handler:
    def __init__(self):
        self.wfile = io.BytesIO()
        self.headers = {}
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass


@pytest.fixture
def enabled_auth(monkeypatch):
    monkeypatch.setattr(auth, 'is_auth_enabled', lambda: True)
    monkeypatch.setattr(auth, 'parse_cookie', lambda handler: None)
    monkeypatch.setattr(auth, 'ensure_trusted_auth_session', lambda handler: None)


@pytest.mark.parametrize('path', ['/api/private', '/v1/documents'])
def test_unauthenticated_api_is_401_json(enabled_auth, path):
    handler = Handler()
    assert auth.check_auth(handler, urlparse(path)) is False
    assert handler.status == 401
    assert handler.headers['Content-Type'] == 'application/json'
    assert json.loads(handler.wfile.getvalue()) == {'error': 'Authentication required'}
    assert 'Location' not in handler.headers


@pytest.mark.parametrize('path', ['/api/private', '/v1/documents'])
def test_profile_denied_api_is_403_json(enabled_auth, monkeypatch, path):
    monkeypatch.setattr(auth, 'ensure_trusted_auth_session', lambda handler: {'profile': 'other'})
    monkeypatch.setattr(auth, 'trusted_session_allows_active_profile', lambda session: False)
    handler = Handler()
    assert auth.check_auth(handler, urlparse(path)) is False
    assert handler.status == 403
    assert handler.headers['Content-Type'] == 'application/json'
    assert json.loads(handler.wfile.getvalue()) == {'error': 'Profile access forbidden'}


@pytest.mark.parametrize('path', ['/documents?x=1&y=2', '/v10/documents', '/v1-lookalike/documents', '/api-lookalike/private'])
def test_page_and_lookalike_paths_still_redirect(enabled_auth, path):
    handler = Handler()
    assert auth.check_auth(handler, urlparse(path)) is False
    assert handler.status == 302
    redirect = urlparse(handler.headers['Location'])
    assert redirect.path == 'login'  # Preserve the existing relative page redirect.
    assert parse_qs(redirect.query)['next'] == [path]
