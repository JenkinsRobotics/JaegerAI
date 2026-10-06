"""A cancel or Global Stop reaches a command that has already started.

The Gateway cancels a request by setting that request's own event. The tool layer
used to poll only a process-wide flag the Gateway never set, so a started shell
command ran to completion after Stop.
"""
import os
import subprocess
import threading
import time

import pytest

from jaeger_agent.core.cancellation import turn_cancellation
from jaeger_agent.util.tool_interrupt import ToolInterrupted, is_interrupted, run_interruptible


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_is_interrupted_follows_the_turns_own_event():
    event = threading.Event()
    assert is_interrupted() is False
    with turn_cancellation(event):
        assert is_interrupted() is False
        event.set()
        assert is_interrupted() is True
    assert is_interrupted() is False          # unbound again outside the turn


def test_a_running_command_and_its_descendants_die_when_the_turn_event_is_set(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    event = threading.Event()
    threading.Timer(0.6, event.set).start()
    started = time.monotonic()
    # sh forks a grandchild (the sleep) and records its pid: the whole tree must go.
    with turn_cancellation(event), pytest.raises(ToolInterrupted):
        run_interruptible(["/bin/sh", "-c", f"sleep 300 & echo $! > {pidfile}; wait"], timeout=60)
    assert time.monotonic() - started < 10
    pid = int(pidfile.read_text().strip())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "the descendant survived the cancel"


def test_another_turns_event_does_not_stop_this_command():
    mine, other = threading.Event(), threading.Event()
    other.set()
    with turn_cancellation(mine):
        proc = run_interruptible(["/bin/sh", "-c", "echo done"], timeout=10)
    assert proc.returncode == 0 and "done" in proc.stdout
