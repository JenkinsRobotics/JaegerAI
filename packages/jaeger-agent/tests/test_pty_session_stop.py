"""A command session dies with the turn that started it, and Global Stop sweeps the rest."""
import os
import threading
import time

from jaeger_agent.core.cancellation import turn_cancellation
from jaeger_agent.tools.pty_exec import PtyManager, kill_all_sessions
import jaeger_agent.tools.pty_exec as pty_exec


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_dead(pid, seconds=6.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end and _alive(pid):
        time.sleep(0.1)
    return not _alive(pid)


def test_a_session_started_in_a_turn_dies_when_that_turn_is_cancelled(tmp_path):
    manager, event = PtyManager(), threading.Event()
    pidfile = tmp_path / "child.pid"
    with turn_cancellation(event):
        out = manager.start(f"sleep 300 & echo $! > {pidfile}; wait", cwd=str(tmp_path), yield_s=0.3)
    sid = out["session_id"]
    session = manager.get(sid)
    child = int(pidfile.read_text().strip())
    assert session.running and _alive(child)

    event.set()                                   # /cancel or Global Stop on that request

    assert _wait_dead(session.proc.pid), "the command survived its turn's cancel"
    assert _wait_dead(child), "a descendant of the command survived"
    session.close()


def test_a_session_of_another_turn_is_left_alone(tmp_path):
    manager, mine, other = PtyManager(), threading.Event(), threading.Event()
    with turn_cancellation(mine):
        out = manager.start("sleep 300", cwd=str(tmp_path), yield_s=0.2)
    other.set()
    time.sleep(0.6)
    session = manager.get(out["session_id"])
    assert session.running
    manager.kill_all()


def test_kill_all_sessions_terminates_every_session_and_reports_survivors(tmp_path, monkeypatch):
    manager = PtyManager()
    monkeypatch.setattr(pty_exec, "_manager", manager)
    pids = []
    for _ in range(2):
        out = manager.start("sleep 300", cwd=str(tmp_path), yield_s=0.2)
        pids.append(manager.get(out["session_id"]).proc.pid)

    result = kill_all_sessions()

    assert result == {"killed": 2, "survivors": []}
    assert all(_wait_dead(p) for p in pids)
    assert manager.ids() == []
