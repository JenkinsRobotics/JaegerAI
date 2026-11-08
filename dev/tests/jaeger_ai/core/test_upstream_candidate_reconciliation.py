"""Combined upstream read markers and candidate durable request ownership."""
import copy

import pytest

from jaeger_ai.core.gateway.session_store import GatewaySessionStore, RequestConflict


def test_read_markers_preserve_frozen_replay_and_session_identity(tmp_path):
    store = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    choices = {'model': 'original-model', 'allowed_tools': [], 'caller': 'owner:cli'}
    original = store.admit_request('first', 'work', request_id='original', requested=choices)
    store.complete_request('original', status='completed', result={'output': 'saved'})
    before = copy.deepcopy(store.get_request('original'))
    marker = store.set_message_read_state('first', {'request_id': 'original', 'role': 'assistant'})
    store.update_metadata('first', {'model': 'changed-default'})
    replay = store.admit_request('first', 'work', request_id='original', requested=choices)
    assert replay['replayed'] and replay['turn_id'] == original['turn_id']
    assert store.get_request('original') == before
    with pytest.raises(RequestConflict):
        store.admit_request('other', 'work', request_id='original', requested=choices)
    assert store.get_session('other') is None
    assert GatewaySessionStore(store.path).message_read_state('first')['event_id'] == marker['event_id']
    assert store.get_session('first')['metadata']['model'] == 'changed-default'


@pytest.mark.parametrize('newer_status', ['running', 'failed', 'cancelled', 'completed'])
def test_marker_events_cannot_replace_admission_chronology(tmp_path, newer_status):
    store = GatewaySessionStore(tmp_path / 'sessions.sqlite3')
    store.admit_request('chat', 'older work', request_id='older')
    store.recover_interrupted_sessions()
    store.acknowledge_unknown('chat', actor='owner', request_id='older')
    store.admit_request('chat', 'newer work', request_id='newer')
    if newer_status != 'running':
        store.complete_request('newer', status=newer_status, result={'output': newer_status})
    before = store.get_session('chat')
    store.set_message_read_state('chat', {'request_id': 'older', 'role': 'user'})
    assert store.get_session('chat')['updated_at'] == before['updated_at']
    store.complete_request('older', status='completed', result={'output': 'late result'})
    assert store.get_session('chat')['status'] == before['status']
    assert store.message_read_state('chat')['unread'] == {'request_id': 'older', 'role': 'user'}
    assert store.get_request('newer')['status'] == ('admitted' if newer_status == 'running' else newer_status)
