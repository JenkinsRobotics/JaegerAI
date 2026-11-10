"""Owned adapter boundary, no provider or private prompt logging."""
import json
import pytest
from dev.tests.fixtures.model_completion import model_completion
from jaeger_agent import JaegerAgent, ProviderAdapter
from jaeger_agent.loop.callbacks import AgentCallbacks
from jaeger_agent.loop.input_outline import input_outline
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore
from jaeger_ai.core.gateway.turn_parts import project_parts


def test_actual_formatted_boundary_persists_only_outline(tmp_path):
    store = GatewaySessionStore(tmp_path / 'gateway.sqlite3')
    store.ensure_session('owned')
    store.admit_request('owned', 'Owned request', request_id='owned-request')
    gateway = JaegerGatewayApp(store=store)
    gateway.app.on_startup.clear()
    callbacks, finish = gateway._turn_stream_callbacks('owned', 'owned-request')
    class Adapter(ProviderAdapter):
        name = 'owned-only'
        def format_messages(self, messages, tools, system):
            # Deliberately replaces original input: observer must see this input.
            return {'system': 'PRIVATE-SYSTEM', 'messages': [
                {'role': 'user', 'content': [{'type': 'text', 'text': 'formatted'},
                    {'type': 'image', 'data': 'SECRET-BYTES'}]}],
                'tools': [{'name': 'SECRET-TOOL'}], 'api_key': 'SECRET-KEY'}
        def call(self, formatted, interrupt_event, **kwargs):
            events = store.activity_history('owned')['events']
            assert any(e['event'] == 'turn.context' for e in events)
            assert formatted['api_key'] == 'SECRET-KEY'
            return {'role': 'assistant', 'content': 'Done'}
        def parse_response(self, raw): return raw
        def supports(self, feature): return False
    agent = JaegerAgent(adapter=Adapter(), tools=[], callbacks=callbacks)
    assert agent.run_turn('ORIGINAL-PRIVATE-INPUT') == 'Done'
    finish()
    events = store.activity_history('owned')['events']
    parts = project_parts(events)
    from jaeger_ai.core.gateway.event_bus import EVENT_TYPES
    assert 'tools.selected' in EVENT_TYPES
    selection = next(p['receipt'] for p in parts if p['type'] == 'tool_selection')
    assert selection['selected_count'] == 0 and selection['tools'] == []
    outline = next(p['outline'] for p in parts if p['type'] == 'model_context')
    assert outline['messages'] == [{'role': 'user', 'text_chars': 9, 'omitted_blocks': 1}]
    assert outline['system_chars'] == 14 and outline['tool_count'] == 1
    assert not any(private in json.dumps(parts) for private in ('PRIVATE', 'SECRET', 'formatted'))
    context_event = next(e for e in events if e['event'] == 'turn.context')
    assert context_event['data']['request_id'] == 'owned-request'
    assert context_event['data']['turn_id'] == store.get_request('owned-request')['turn_id']
    for i in range(6):
        store.append_event('owned', 'turn.delta', {'request_id':'owned-request', 'delta':'.'})
    store.complete_request('owned-request', status='completed', result={}, assistant_text='Done')
    assert any(p['type'] == 'tool_selection' and p['receipt'] == selection for p in store.get_session('owned')['messages'][-1]['parts'])
    assert any(p['type'] == 'model_context' and p['outline'] == outline for p in store.get_session('owned')['messages'][-1]['parts'])


def test_unsupported_and_untrusted_shapes_do_not_echo_values():
    assert input_outline('PRIVATE-PROMPT')['shape'] == 'unsupported'
    outline = input_outline({'messages': [{'role': 'PRIVATE', 'content': [{'type': 'thinking', 'text': 'PRIVATE'}]}]})
    assert outline['messages'] == [{'role': 'other', 'text_chars': 0, 'omitted_blocks': 1}]
    assert 'PRIVATE' not in json.dumps(outline)
    seen = []
    def broken(value):
        seen.append(value)
        raise RuntimeError('observer failure')
    AgentCallbacks(model_input=broken).on_model_input({'prompt': 'private'})
    assert seen[0]['messages'][0]['text_chars'] == 7


@pytest.mark.asyncio
async def test_model_only_payload_is_observed_before_http_without_secrets(tmp_path, monkeypatch, model_completion):
    store = GatewaySessionStore(tmp_path / 'model-only.sqlite3')
    store.ensure_session('owned')
    store.admit_request('owned', 'Owned request', request_id='owned-request')
    gateway = JaegerGatewayApp(store=store)
    gateway.app.on_startup.clear()
    monkeypatch.setenv('OLLAMA_API_KEY', 'owned-dummy-not-a-real-key')
    assert await gateway._model_chat('PRIVATE-QUESTION', model='owned-model',
        system_prompt='PRIVATE-SYSTEM', context_ids=('owned','owned-request')) == 'remembered'
    event = store.activity_history('owned')['events'][-1]
    assert event['data']['outline']['messages'][-1]['text_chars'] == 16
    assert event['data']['turn_id'] == store.get_request('owned-request')['turn_id']
    assert 'PRIVATE' not in json.dumps(event) and 'owned-dummy' not in json.dumps(event)
