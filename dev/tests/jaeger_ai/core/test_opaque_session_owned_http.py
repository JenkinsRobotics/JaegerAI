"""Opaque historic identity survives encoded routes on an authenticated owned stack."""
import json
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


def test_opaque_session_link_preserves_exact_identity_through_gateway_and_webui(tmp_path):
    stack = OwnedGateway(tmp_path, webui=True)
    session_id = 'historic / session ? # % café'
    encoded = quote(session_id, safe='')
    # Same URLSearchParams round trip as conversationPath and encodeURIComponent
    # path segment as GatewaySource.session. Neither value is a filesystem path.
    link = '/chat?' + urlencode({'session': session_id})
    assert parse_qs(urlsplit(link).query)['session'] == [session_id]
    path = '/v1/sessions/' + encoded
    try:
        stack.start()
        status, created = stack.request('/v1/sessions', {'session_id': session_id, 'profile': 'jaeger'})
        assert status == 201 and created['session_id'] == session_id
        stack.request(path + '/turns', {'text': 'Say CONTRACT-ANSWER', 'request_id': 'opaque-original'})
        assert stack.wait_for_terminal(encoded, 'opaque-original')['status'] == 'completed'
        _, transcript = stack.request(path)
        assert transcript['session_id'] == session_id
        assert [row['role'] for row in transcript['messages']] == ['user', 'assistant']
        _, selected = stack.request('/v1/operator/session-state')
        assert selected['active_session_id'] == session_id
        browser = build_opener(HTTPCookieProcessor(CookieJar()))
        request = Request(stack.webui_url + '/api/auth/login',
                          data=json.dumps({'password': 'synthetic-contract-password'}).encode(),
                          headers={'Content-Type': 'application/json'})
        with browser.open(request, timeout=5) as response:
            assert response.status == 200
        with browser.open(stack.webui_url + link, timeout=5) as response:
            assert response.status == 200
        with browser.open(stack.webui_url + path, timeout=5) as response:
            proxied = json.load(response)
        assert proxied['session_id'] == session_id
        assert proxied['messages'] == transcript['messages']
        assert stack.request('/v1/operator/session-state')[1] == selected
        # The same decoded identity remains inaccessible to prefix-limited bots.
        with pytest.raises(HTTPError) as denied:
            stack.request(path, caller='mcp')
        assert denied.value.code == 403
        assert stack.request('/v1/operator/session-state')[1] == selected
    finally:
        stack.stop()
