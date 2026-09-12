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


def test_structured_halt_is_failed_even_when_text_exists_and_error_is_null(tmp_path):
    ledger = NativeTurns(tmp_path)
    ledger.accept('halted', 'dispatcher')
    frame = {'text': '[halted: repeated failure]', 'error': None,
             'halt_reason': 'hit the same web_search failure 2 times', 'halt_code': 'repeated_tool_failure'}
    ledger.finish('halted', 'dispatcher', frame)
    assert ledger.get('halted', 'dispatcher')['status'] == 'failed'
    # A legacy completed row retains its bytes but is interpreted correctly.
    with ledger.transaction() as conn:
        conn.execute("UPDATE turns SET status='completed' WHERE id='halted'")
    assert NativeTurns(tmp_path, read_only=True).get('halted', 'dispatcher')['status'] == 'failed'


def test_read_only_receipt_probe_does_not_create_state(tmp_path):
    import sqlite3
    root = tmp_path / 'absent'
    reader = NativeTurns(root, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        reader.get('unknown', 'dispatcher')
    assert not root.exists()


@pytest.mark.parametrize('identity', ['', '../escape', 'x' * 129])
def test_invalid_native_identity_is_rejected(tmp_path, identity):
    with pytest.raises(ValueError): NativeTurns(tmp_path).accept(identity, 'session')


def test_session_tool_grant_survives_reopen_and_cannot_expand(tmp_path):
    from jaeger_ai.core.runtime.native_turns import NativeTurns
    first = NativeTurns(tmp_path, epoch='first')
    first.bind_tool_grant('specialist:child', ['web_search'])
    restarted = NativeTurns(tmp_path, epoch='second')
    restarted.bind_tool_grant('specialist:child', ['web_search', 'web_search'])
    for grant in (None, ['web_search', 'run_shell'], []):
        with pytest.raises(ValueError):
            restarted.bind_tool_grant('specialist:child', grant)
    restarted.bind_tool_grant('specialist:new', [])
    restarted.bind_tool_grant('dispatcher', None)
