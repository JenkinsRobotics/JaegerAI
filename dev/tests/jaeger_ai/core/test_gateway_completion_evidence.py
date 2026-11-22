"""A finished request and an independently checked objective are different facts."""

from types import SimpleNamespace

import pytest

from jaeger_ai.core.entity.runtime import EntityRuntime, PreparedTurn
from jaeger_ai.core.gateway.server import JaegerGatewayApp
from jaeger_ai.core.gateway.session_store import GatewaySessionStore


@pytest.mark.asyncio
async def test_owner_identity_and_unverified_completion_survive_gateway_receipt(tmp_path, monkeypatch):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'gateway.sqlite3'))
    gateway.store.ensure_session('s')
    runtime = SimpleNamespace(
        prepare_turn=lambda text, **kwargs: PreparedTurn(
            prompt=text, event=None, user_text=text, session_id=kwargs['session_id']),
        finish_turn=lambda *a, **k: None,
    )
    monkeypatch.setattr(EntityRuntime, 'get_singleton', classmethod(lambda cls, *a, **k: runtime))
    monkeypatch.setattr(gateway, '_resolve_session_agent', lambda _: None)
    monkeypatch.setattr(gateway, '_schedule_summary', lambda _: None)

    def worker(prompt, *, on_model, callbacks, **kwargs):
        on_model('configured-route')
        callbacks.on_model_call_start()
        callbacks.on_stream_delta('Here is the proposal.')
        callbacks.on_model_call_done({'actual_model': 'provider-served-model'})
        return {'text': 'Here is the proposal.', 'status': 'completed', 'verification': {'ok': True}}

    runtime.run_subordinate_react = worker
    monkeypatch.setattr(gateway, '_maybe_queue_skill_review', lambda *a, **k: None)
    monkeypatch.setattr(gateway, '_maybe_queue_memory_review', lambda *a, **k: None)
    admitted = gateway.store.admit_request('s', 'What is your proposal?', request_id='r')
    await gateway._execute_turn('s', admitted['turn_id'], 'What is your proposal?',
                                request_id='r', execution=admitted['execution'])
    result = gateway.store.get_request('r')['result']
    assert result['status'] == 'completed'
    assert result['status_scope'] == 'request_execution'
    assert result['model'] == 'configured-route'
    assert result['actual_model'] == 'provider-served-model'
    assert result['model_identity_scope'] == 'provider_reported'
    assert result['verification']['status'] == 'not_performed'
    assert result['verification']['worker_report'] == {'ok': True}
    assert gateway.task_owner.store.list_tasks() == []
    events = gateway.store.replay_events('s')['events']
    deltas = [event['data'] for event in events if event['event'] == 'turn.delta']
    assert len(deltas) == 1
    assert deltas[0]['delta'] == result['output'] and deltas[0]['item_id']
    message = gateway.store.get_session('s')['messages'][-1]
    identity = next(p for p in message['parts'] if p['type'] == 'model_identity')
    assert identity['actual_model'] == 'provider-served-model'


def test_failed_request_keeps_unverified_outcome_and_private_claims_out_of_status(tmp_path, monkeypatch):
    gateway = JaegerGatewayApp(store=GatewaySessionStore(tmp_path / 'gateway.sqlite3'))
    gateway.store.ensure_session('s')
    gateway.store.admit_request('s', 'request', request_id='r')
    monkeypatch.setattr(gateway, '_drain_session_queue', lambda _: None)
    gateway._persist_terminal('r', 's', 'failed', {'error': 'tool failed'}, record_entity_event=False)
    row = gateway.store.get_request('r')
    assert row['status'] == 'failed'
    assert row['result']['verification']['status'] == 'not_performed'
    assert row['result']['status_scope'] == 'request_execution'
