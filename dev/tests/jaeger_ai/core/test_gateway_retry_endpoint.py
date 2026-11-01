"""Retry reuses a visible user turn and refuses invalid admissions."""
import json
from types import SimpleNamespace
import pytest
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore

@pytest.mark.asyncio
async def test_retry_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_HOME', str(tmp_path))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'sessions.db'))
    gateway.app.on_startup.clear()
    gateway._start_admitted_turn = lambda *args: None
    gateway.store.ensure_session('chat')
    try:
        missing = SimpleNamespace(match_info={'id': 'missing'})
        chat = SimpleNamespace(match_info={'id': 'chat'})
        assert (await gateway.handle_retry_session(missing)).status == 404
        assert (await gateway.handle_retry_session(chat)).status == 404
        gateway.store.admit_request('chat', 'hello', request_id='original')
        assert (await gateway.handle_retry_session(chat)).status == 409
        gateway.store.complete_request('original', status='completed', result={'answer': 'old'}, assistant_text='old')
        response = await gateway.handle_retry_session(chat)
        assert response.status == 202
        body = json.loads(response.text)
        assert body['request_id'] != 'original'
        messages = gateway.store.get_session('chat')['messages']
        assert [(m['role'], m['content']) for m in messages] == [('user', 'hello')]
        assert (await gateway.handle_retry_session(chat)).status == 409
    finally:
        await gateway.app.cleanup()

@pytest.mark.asyncio
async def test_retry_twice_reuses_one_visible_turn(tmp_path, monkeypatch):
    monkeypatch.setenv('JAEGER_HOME', str(tmp_path))
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'sessions.db'))
    gateway.app.on_startup.clear()
    gateway._start_admitted_turn = lambda *args: None
    gateway.store.ensure_session('chat')
    try:
        gateway.store.admit_request('chat', 'hello', request_id='original')
        gateway.store.complete_request('original', status='completed', result={'answer': 'old'}, assistant_text='old')
        first = json.loads((await gateway.handle_retry_session(SimpleNamespace(match_info={'id': 'chat'}))).text)
        gateway.store.complete_request(first['request_id'], status='completed', result={'answer': 'middle'}, assistant_text='middle')
        second_response = await gateway.handle_retry_session(SimpleNamespace(match_info={'id': 'chat'}))
        assert second_response.status == 202
        second = json.loads(second_response.text)
        gateway.store.complete_request(second['request_id'], status='completed', result={'answer': 'latest'}, assistant_text='latest')
        messages = gateway.store.get_session('chat')['messages']
        assert [(m['role'], m['content']) for m in messages] == [('user', 'hello'), ('assistant', 'latest')]
        assert messages[0]['request_id'] == second['request_id']
        assert gateway.store.get_request('original')['status'] == 'completed'
        assert gateway.store.get_request(first['request_id'])['status'] == 'completed'
    finally:
        await gateway.app.cleanup()
