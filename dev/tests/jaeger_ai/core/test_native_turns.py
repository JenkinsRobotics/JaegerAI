import pytest

from jaeger_ai.core.runtime.native_turns import NativeTurns


def test_native_terminal_receipt_survives_bridge_restart(tmp_path):
    first = NativeTurns(tmp_path, epoch='first')
    first.accept('turn', 'session')
    first.finish('turn', 'session', {'text': 'result', 'error': None, 'cancelled': False})
    saved = NativeTurns(tmp_path, epoch='second').get('turn', 'session')
    assert saved['status'] == 'completed'
    assert saved['reply']['text'] == 'result'
    assert saved['execution_unknown'] is False
    assert (tmp_path / 'native-turns.sqlite3').stat().st_mode & 0o777 == 0o600


def test_old_active_and_absent_turns_never_imply_completion(tmp_path):
    first = NativeTurns(tmp_path, epoch='first')
    first.accept('turn', 'session')
    assert first.get('turn', 'session')['status'] == 'queued'
    recovered = NativeTurns(tmp_path, epoch='second')
    assert recovered.get('turn', 'session')['status'] == 'unknown'
    assert recovered.get('turn', 'session')['execution_unknown']
    assert recovered.get('absent', 'session')['status'] == 'unknown'


def test_duplicate_turn_and_wrong_session_cannot_execute_or_read_again(tmp_path):
    ledger = NativeTurns(tmp_path, epoch='first')
    ledger.accept('turn', 'one')
    ledger.finish('turn', 'one', {'text': 'private', 'error': None})
    with pytest.raises(ValueError, match='Duplicate'):
        NativeTurns(tmp_path, epoch='second').accept('turn', 'one')
    assert ledger.get('turn', 'other')['status'] == 'unknown'
    assert 'private' not in str(ledger.get('turn', 'other'))


def test_another_bridge_epoch_cannot_invent_terminal_evidence(tmp_path):
    NativeTurns(tmp_path, epoch='first').accept('turn', 'session')
    with pytest.raises(ValueError, match='owner'):
        NativeTurns(tmp_path, epoch='second').finish('turn', 'session', {'text': 'fake'})


def test_queue_is_bounded_before_native_dispatch(tmp_path):
    ledger = NativeTurns(tmp_path, epoch='first', max_pending=1)
    ledger.accept('one', 'session')
    with pytest.raises(RuntimeError, match='capacity'):
        ledger.accept('two', 'another')
    ledger.finish('one', 'session', {'text': 'done'})
    ledger.accept('two', 'another')


@pytest.mark.parametrize('identity', ['', '../escape', 'x' * 129])
def test_invalid_native_identity_is_rejected(tmp_path, identity):
    with pytest.raises(ValueError): NativeTurns(tmp_path).accept(identity, 'session')
