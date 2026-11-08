"""Default UI home -> authenticated proxy -> real owned resident, scripted provider only."""
import json
import re
from html import unescape
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest

from dev.tests.fixtures.owned_gateway import OwnedGateway
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

pytestmark = [pytest.mark.integration, pytest.mark.subprocess]


@pytest.mark.parametrize('entry', ['home', 'new-chat', 'default'])
def test_default_lead_proxy_receipt_survives_owned_restart_without_reexecution(tmp_path, entry):
    stack = OwnedGateway(tmp_path, webui=True)
    browser = build_opener(HTTPCookieProcessor(CookieJar()))
    try:
        stack.start()
        with browser.open(Request(stack.webui_url + '/api/auth/login',
                data=json.dumps({'password': 'synthetic-contract-password'}).encode(),
                headers={'Content-Type': 'application/json'}), timeout=5) as response:
            assert json.load(response) == {'ok': True}
        def csrf():
            with browser.open(stack.webui_url + '/', timeout=5) as response:
                return unescape(re.search(r'<meta name="jaeger-csrf" content="([^"]*)">', response.read().decode()).group(1))
        def proxy(path, body=None):
            headers = {'Content-Type': 'application/json'}
            if body is not None:
                headers['X-Hermes-CSRF-Token'] = csrf()
            try:
                with browser.open(Request(stack.webui_url + ('/v1' if path.startswith('/agents') else '/api/jaeger') + path,
                        data=None if body is None else json.dumps(body).encode(), headers=headers), timeout=10) as response:
                    return json.load(response)
            except HTTPError as exc:
                pytest.fail(f'{path}: {exc.code} {exc.read().decode()}\n' + (stack.root / 'gateway.log').read_text())
        # The shared UI loads its canonical roster before selecting/creating a chat.
        proxy('/agents')
        if entry == 'home':
            session = proxy('/agents/native:jaeger/home')
        else:
            import uuid
            session = proxy('/sessions', {'session_id': str(uuid.uuid4()), 'source': 'webui',
                'title': 'New chat', **({'agent_id': 'native:jaeger'} if entry == 'new-chat' else {})})
        sid = session['session_id']
        resolved = proxy('/sessions/' + sid)
        assert resolved['agent_id'] == 'native:jaeger'
        assert resolved['role'] == 'lead'
        store = GatewaySessionStore(tmp_path / 'gateway_sessions.sqlite3')
        metadata = resolved['metadata']
        if not any(metadata.get(key) for key in ('home', 'agent_pinned', 'route_checked')):
            # An implicit first turn still owns legitimate one-time triage.
            # It cannot claim a stable lead journal until that existing route commits.
            first = {'text': 'Say CONTRACT-ANSWER', 'request_id': 'route-first'}
            assert proxy('/sessions/' + sid + '/turns', first)['request_id'] == 'route-first'
            assert stack.wait_for_terminal(sid, 'route-first')['status'] == 'completed'
            assert not store.has_owner_request_journal('route-first')
            assert proxy('/sessions/' + sid)['metadata']['route_checked'] is True
        body = {'text': 'Say CONTRACT-ANSWER', 'request_id': 'default-lead'}
        assert proxy('/sessions/' + sid + '/turns', body)['request_id'] == 'default-lead'
        terminal = stack.wait_for_terminal(sid, 'default-lead')
        assert terminal['status'] == 'completed'
        store = GatewaySessionStore(tmp_path / 'gateway_sessions.sqlite3')
        # Read the actual producer's journal without substituting runtime/proof machinery.
        with store._get_conn() as conn:
            row = conn.execute('SELECT identity_json, terminal_json FROM owner_request_journal WHERE request_id=?', ('default-lead',)).fetchone()
            assert row is not None
            identity, proof = json.loads(row[0]), json.loads(row[1])
        assert json.loads(identity['execution_json'])['_owner_agent'] == {
            'id': 'native:jaeger', 'kind': 'jaeger_native', 'role': 'lead', 'disabled': False}
        assert proof['result']['output'] == 'CONTRACT-ANSWER'
        assert proof['status'] == 'completed' and proof['effects_settled'] is True
        calls = (tmp_path / 'provider-calls.jsonl').read_text()
        messages = proxy('/sessions/' + sid)['messages']
        stack.stop()
        stack.start()
        assert proxy('/sessions/' + sid)['messages'] == messages
        replay = proxy('/sessions/' + sid + '/turns', body)
        assert replay['replayed'] is True
        assert (tmp_path / 'provider-calls.jsonl').read_text() == calls
        assert stack.wait_for_terminal(sid, 'default-lead')['result'] == terminal['result']
    finally:
        stack.stop()
