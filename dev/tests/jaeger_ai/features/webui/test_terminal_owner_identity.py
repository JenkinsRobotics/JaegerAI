from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from jaeger_ai.features.webui.api import terminal

def test_owner_registry_preserves_opaque_identity(monkeypatch, tmp_path):
    exact = ' historic / α '
    matching = SimpleNamespace(session_id=exact, workspace=str(tmp_path), is_alive=lambda: True)
    foreign = SimpleNamespace(session_id=exact.strip(), workspace=str(tmp_path), is_alive=lambda: True)
    monkeypatch.setattr(terminal, '_TERMINALS', {exact: matching, exact.strip(): foreign})
    monkeypatch.setattr(terminal, '_set_size', Mock())
    monkeypatch.setattr(terminal, '_enforce_terminal_cap', Mock())
    monkeypatch.setattr(terminal.os, 'openpty', Mock(side_effect=AssertionError('No real PTY allowed')))
    assert terminal.start_terminal(exact, tmp_path) is matching

import threading
import pytest

@pytest.fixture
def owners(monkeypatch, tmp_path):
    def owner(sid, fd):
        return SimpleNamespace(session_id=sid, workspace=str(tmp_path), is_alive=lambda: True,
                               io_lock=threading.RLock(), closed=threading.Event(), master_fd=fd,
                               subscribe=Mock(return_value=object()))
    exact = ' historic / α '
    matching, foreign = owner(exact, 101), owner(exact.strip(), 102)
    monkeypatch.setattr(terminal, '_TERMINALS', {exact: matching, exact.strip(): foreign})
    monkeypatch.setattr(terminal, '_set_size', Mock())
    monkeypatch.setattr(terminal, '_enforce_terminal_cap', Mock())
    monkeypatch.setattr(terminal, '_teardown_terminal', Mock())
    monkeypatch.setattr(terminal.os, 'write', Mock())
    monkeypatch.setattr(terminal.os, 'openpty', Mock(side_effect=AssertionError('No real PTY allowed')))
    return exact, matching, foreign


def test_all_terminal_operations_preserve_distinct_opaque_keys(owners, tmp_path):
    sid, matching, foreign = owners
    assert terminal.start_terminal(sid, tmp_path) is matching
    assert terminal.get_terminal(sid) is matching
    attached, _ = terminal.attach_terminal(sid)
    assert attached is matching
    foreign.subscribe.assert_not_called()
    terminal.write_terminal(sid, 'command')
    terminal.os.write.assert_called_once_with(matching.master_fd, b'command')
    terminal.resize_terminal(sid, 25, 81)
    assert terminal._set_size.call_args.args == (matching, 25, 81)
    assert terminal.close_terminal(sid)
    terminal._teardown_terminal.assert_called_once_with(matching)
    assert terminal.get_terminal(foreign.session_id) is foreign


@pytest.mark.parametrize('invalid', [None, 12, '', 'x\n', 'x\x00', 'x\x7f', 'x' * 257])
@pytest.mark.parametrize('operation', ['start', 'get', 'attach', 'write', 'resize', 'close'])
def test_invalid_identity_rejected_without_alias_or_side_effect(owners, tmp_path, invalid, operation):
    calls = {
        'start': lambda: terminal.start_terminal(invalid, tmp_path),
        'get': lambda: terminal.get_terminal(invalid),
        'attach': lambda: terminal.attach_terminal(invalid),
        'write': lambda: terminal.write_terminal(invalid, 'x'),
        'resize': lambda: terminal.resize_terminal(invalid, 24, 80),
        'close': lambda: terminal.close_terminal(invalid),
    }
    with pytest.raises(ValueError, match='Invalid terminal session_id'):
        calls[operation]()
    assert len(terminal._TERMINALS) == 2
    terminal.os.openpty.assert_not_called()
    terminal.os.write.assert_not_called()
    terminal._teardown_terminal.assert_not_called()


@pytest.mark.parametrize('operation', ['start', 'get', 'attach', 'write', 'resize', 'close'])
def test_mismatched_registry_owner_fails_closed(owners, tmp_path, operation):
    sid, matching, foreign = owners
    terminal._TERMINALS[sid] = foreign
    calls = {'start': lambda: terminal.start_terminal(sid, tmp_path),
             'get': lambda: terminal.get_terminal(sid), 'attach': lambda: terminal.attach_terminal(sid),
             'write': lambda: terminal.write_terminal(sid, 'x'),
             'resize': lambda: terminal.resize_terminal(sid, 24, 80), 'close': lambda: terminal.close_terminal(sid)}
    with pytest.raises(ValueError, match='identity mismatch'):
        calls[operation]()
    terminal.os.openpty.assert_not_called()
    terminal.os.write.assert_not_called()
    terminal._teardown_terminal.assert_not_called()


def test_new_terminal_registers_exact_key_with_fully_mocked_spawn(monkeypatch, tmp_path):
    sid = ' newly created / α '
    monkeypatch.setattr(terminal, '_TERMINALS', {})
    for name in ('_set_size', '_enforce_terminal_cap', '_ensure_spawn_supervisor', '_ensure_terminal_reaper', '_set_nonblocking'):
        monkeypatch.setattr(terminal, name, Mock())
    monkeypatch.setattr(terminal.os, 'openpty', Mock(return_value=(101, 102)))
    monkeypatch.setattr(terminal.os, 'close', Mock())
    monkeypatch.setattr(terminal.threading, 'Thread', Mock())
    proc = Mock()
    def accept(request):
        request.proc = proc
        request.done.set()
    monkeypatch.setattr(terminal, '_spawn_queue', SimpleNamespace(put=accept))
    created = terminal.start_terminal(sid, tmp_path)
    assert created.session_id == sid
    assert terminal._TERMINALS == {sid: created}
    assert terminal.get_terminal(sid.strip()) is None
    assert terminal.attach_terminal(sid)[0] is created
