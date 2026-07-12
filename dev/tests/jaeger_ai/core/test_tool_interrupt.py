"""Mid-tool interrupt — long-running tools stop when the turn is cancelled.

Audit gap #6. JROS only checked the cancel flag *between* agent-loop
nodes, so a 60-second ``run_shell`` or a slow ``web_fetch`` ran to
completion before a cancel was honoured. ``core/tool_interrupt.py`` gives
those tools one shared interrupt flag to poll mid-execution.

These tests cover the signal contract, the ``run_interruptible``
subprocess helper (normal exit / timeout / interrupt / child actually
killed), the wired-up tools, and the fact that the turn cancel scope and
the tool-interrupt flag are the same Event.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from jaeger_ai.core.runtime import tool_interrupt
from jaeger_ai.agent import tools
from jaeger_ai.core.runtime.tool_interrupt import ToolInterrupted, run_interruptible


@pytest.fixture(autouse=True)
def _clean_interrupt():
    """No test may leak a set interrupt flag into the next one."""
    tool_interrupt.clear_interrupt()
    yield
    tool_interrupt.clear_interrupt()


def _interrupt_after(delay: float) -> threading.Timer:
    """Fire ``request_interrupt`` from a background thread after ``delay``."""
    timer = threading.Timer(delay, tool_interrupt.request_interrupt)
    timer.daemon = True
    timer.start()
    return timer


# ── signal contract ─────────────────────────────────────────────────


def test_set_clear_cycle() -> None:
    assert not tool_interrupt.is_interrupted()
    tool_interrupt.request_interrupt()
    assert tool_interrupt.is_interrupted()
    tool_interrupt.clear_interrupt()
    assert not tool_interrupt.is_interrupted()


def test_begin_scope_clears_a_stale_interrupt() -> None:
    # A cancel left over from a prior turn must not bleed into the next.
    tool_interrupt.request_interrupt()
    ev = tool_interrupt.begin_scope()
    assert not ev.is_set()
    assert not tool_interrupt.is_interrupted()


def test_begin_scope_returns_the_one_shared_event() -> None:
    assert tool_interrupt.begin_scope() is tool_interrupt.get_event()


def test_raise_if_interrupted() -> None:
    tool_interrupt.raise_if_interrupted()  # clear → silent no-op
    tool_interrupt.request_interrupt()
    with pytest.raises(ToolInterrupted):
        tool_interrupt.raise_if_interrupted()


# ── run_interruptible — the subprocess helper ────────────────────────


def test_run_interruptible_returns_completed_process() -> None:
    proc = run_interruptible(
        [sys.executable, "-c", "print('hello')"], timeout=10,
    )
    assert isinstance(proc, subprocess.CompletedProcess)
    assert proc.returncode == 0
    assert "hello" in proc.stdout


def test_run_interruptible_raises_on_timeout() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_interruptible(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.5,
        )


def test_run_interruptible_aborts_on_interrupt() -> None:
    timer = _interrupt_after(0.3)
    started = time.monotonic()
    try:
        with pytest.raises(ToolInterrupted):
            run_interruptible(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout=30,
            )
    finally:
        timer.cancel()
    # Bailed far short of the 10s sleep and the 30s timeout.
    assert time.monotonic() - started < 3.0


# ── wired tools ──────────────────────────────────────────────────────


def test_run_python_interrupt_kills_the_child(tmp_path) -> None:
    # The child writes a marker only *after* a 2s sleep. If interrupt
    # truly kills it, that delayed write can never land.
    marker = tmp_path / "marker.txt"
    code = (
        "import time\n"
        "time.sleep(2)\n"
        f"open({str(marker)!r}, 'w').write('done')\n"
    )
    timer = _interrupt_after(0.3)
    try:
        result = tools.run_python(code, timeout_s=30)
    finally:
        timer.cancel()
    assert result["interrupted"] is True
    assert result["ok"] is False
    assert result["exit_code"] == 130
    # Wait past the child's own sleep — the marker must still be absent.
    time.sleep(2.3)
    assert not marker.exists()


def test_run_python_uninterrupted_still_works() -> None:
    # The ordinary path must be untouched by the interrupt plumbing.
    result = tools.run_python("print(6 * 7)", timeout_s=10)
    assert result["ok"] is True
    assert result["interrupted"] is False
    assert "42" in result["stdout"]


def test_run_shell_honors_interrupt() -> None:
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        use_policy,
    )

    timer = _interrupt_after(0.3)
    started = time.monotonic()
    try:
        with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
            result = tools.run_shell("sleep 10", timeout_s=30)
    finally:
        timer.cancel()
    assert result["interrupted"] is True
    assert result["ok"] is False
    assert result["exit_code"] == 130
    assert time.monotonic() - started < 3.0


# ── turn cancel scope unification ────────────────────────────────────


def test_turn_cancel_scope_is_the_interrupt_flag() -> None:
    from jaeger_ai.main import begin_turn_cancel_scope, request_turn_cancel

    ev = begin_turn_cancel_scope()
    # The turn's cancel Event and the tool-interrupt flag are one object.
    assert ev is tool_interrupt.get_event()
    assert not tool_interrupt.is_interrupted()
    request_turn_cancel()
    # Cancelling the turn is now visible to a tool polling is_interrupted().
    assert tool_interrupt.is_interrupted()
