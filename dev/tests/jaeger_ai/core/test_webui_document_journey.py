"""Owned HTTP document journey, auth/CSRF and restart; no browser/provider calls."""
import json
import re
from html import unescape
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_owned_webui_document_crud_conflicts_and_restart(tmp_path, monkeypatch):
    # WebUI's legacy document override and the canonical lock root must agree.
    for name in ('JAEGER_STATE_HOME', 'JAEGER_STATE_DIR', 'JAEGER_HOME'):
        monkeypatch.setenv(name, str(tmp_path))
    stack = OwnedGateway(tmp_path, webui=True)
    browser = build_opener(HTTPCookieProcessor(CookieJar()))
    csrf = None

    def request(path, method='GET', body=None, *, token=True):
        headers = {'Content-Type': 'application/json'}
        if token and csrf:
            headers['X-Hermes-CSRF-Token'] = csrf
        req = Request(stack.webui_url + path, method=method, headers=headers,
                      data=None if body is None else json.dumps(body).encode())
        try:
            with browser.open(req, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def load_csrf():
        with browser.open(stack.webui_url + '/', timeout=5) as response:
            markup = response.read().decode()
        match = re.search(r'<meta name="jaeger-csrf" content="([^"]*)">', markup)
        assert match is not None
        value = unescape(match.group(1))
        assert value
        return value

    try:
        stack.start()
        with pytest.raises(HTTPError) as denied:
            urlopen(stack.webui_url + '/v1/documents', timeout=5)
        assert denied.value.code == 401
        assert request('/api/auth/login', 'POST', {'password': 'synthetic-contract-password'}, token=False) == (200, {'ok': True})
        csrf = load_csrf()
        assert request('/v1/documents', 'POST', {'body': 'no-CSRF'}, token=False)[0] == 403
        assert request('/v1/documents') == (200, {'documents': []})

        status, original = request('/v1/documents', 'POST', {'title': 'Synthetic acceptance', 'body': '# Initial\nSynthetic only.'})
        assert status == 201, original
        path = '/v1/documents/' + original['id']
        assert request(path) == (200, original)
        status, winner = request(path, 'PUT', {'title': 'Synthetic saved', 'body': '# Winner\nPersist exactly: café 🧪', 'expected_updated_at': original['updated_at']})
        assert status == 200, winner
        assert winner['updated_at'] > original['updated_at']
        assert winner['created_at'] == original['created_at']
        assert winner['body'] == '# Winner\nPersist exactly: café 🧪'
        assert request(path) == (200, winner)
        status, stale = request(path, 'PUT', {'body': 'stale overwrite', 'expected_updated_at': original['updated_at']})
        assert status == 409, stale
        assert stale['current'] == winner
        status, stale_delete = request(path, 'DELETE', {'expected_updated_at': original['updated_at']})
        assert status == 409, stale_delete
        assert stale_delete['current'] == winner
        assert request(path) == (200, winner)
        assert json.loads((tmp_path / 'documents' / (winner['id'] + '.json')).read_text()) == winner

        old_process = stack.process
        identity = stack.identity
        stack.stop()
        assert old_process.poll() is not None
        stack.start()
        assert stack.process is not old_process
        assert stack.identity == identity
        # Cookie authentication and exact document payload survive both servers.
        assert request(path) == (200, winner)
        csrf = load_csrf()
        assert request(path, 'DELETE', {'expected_updated_at': winner['updated_at']}, token=False)[0] == 403
        assert request(path) == (200, winner)
        assert request(path, 'DELETE', {'expected_updated_at': winner['updated_at']}) == (200, {'deleted': winner['id']})
        assert request(path)[0] == 404
        assert request('/v1/documents') == (200, {'documents': []})
        assert not (tmp_path / 'documents' / (winner['id'] + '.json')).exists()
    finally:
        stack.stop()
