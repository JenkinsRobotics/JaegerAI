"""Persistent PTY command sessions: real processes, no mocks."""

from __future__ import annotations

import os
import time

import pytest

from jaeger_agent.tools import pty_exec
from jaeger_agent.tools.pty_exec import PtyManager, clean_output, elide


@pytest.fixture
def mgr():
    manager = PtyManager()
    yield manager
    manager.kill_all()


def test_a_finished_command_returns_output_and_exit_code_without_a_session(mgr):
    out = mgr.start("echo hello; echo err >&2", cwd=None, yield_s=5)
    assert out["ok"] is True and out["exit_code"] == 0
    assert "hello" in out["output"] and "err" in out["output"]
    assert "session_id" not in out and mgr.ids() == []


def test_a_failing_command_reports_its_exit_code(mgr):
    out = mgr.start("exit 3", cwd=None, yield_s=5)
    assert out["exit_code"] == 3 and out["ok"] is False


def test_a_running_command_keeps_a_session_that_can_be_polled_to_completion(mgr):
    started = mgr.start("sleep 0.6; echo finished", cwd=None, yield_s=0.1)
    sid = started["session_id"]
    assert "exit_code" not in started and mgr.ids() == [sid]
    done = mgr.poll(sid, 5)
    assert "finished" in done["output"] and done["exit_code"] == 0
    assert mgr.ids() == []
    assert "no live command session" in mgr.poll(sid, 0.1)["error"]


def test_interactive_input_round_trips_through_the_terminal(mgr):
    started = mgr.start('printf "name? "; read n; echo "hi $n"', cwd=None, yield_s=1)
    assert "name?" in started["output"]
    reply = mgr.send(started["session_id"], "bob\n", 5)
    assert "hi bob" in reply["output"] and reply["exit_code"] == 0


def test_a_repl_keeps_state_between_calls(mgr):
    started = mgr.start("python3 -u -i -q", cwd=None, yield_s=1)
    sid = started["session_id"]
    mgr.send(sid, "x = 21\n", 1)
    out = mgr.send(sid, "print(x * 2)\n", 3)
    assert "42" in out["output"]
    mgr.send(sid, "exit()\n", 3)


def test_ctrl_c_interrupts_the_foreground_process(mgr):
    started = mgr.start("sleep 60", cwd=None, yield_s=1.0)
    sid = started["session_id"]
    out = mgr.send(sid, "\x03", 8)
    # The terminal echoes "^C" and goes quiet before a loaded machine has finished
    # ending the process, so wait for the exit itself.
    for _ in range(20):
        if "exit_code" in out:
            break
        out = mgr.poll(sid, 0.5)
    assert out.get("exit_code") not in (None, 0), out
    assert mgr.ids() == []


def test_kill_stops_the_process_group_and_frees_the_session(mgr):
    started = mgr.start("sleep 60 & sleep 60", cwd=None, yield_s=0.3)
    sid = started["session_id"]
    session = mgr.get(sid)
    pid = session.proc.pid
    assert mgr.kill(sid)["killed"] == sid
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)  # nothing in the group survived
    assert mgr.kill(sid)["ok"] is False


def test_output_is_clean_text_not_terminal_control_codes(mgr):
    out = mgr.start(r"printf '\033[31mred\033[0m\nprogress 10%%\rprogress 100%%\n'", cwd=None, yield_s=5)
    assert out["output"].splitlines()[:2] == ["red", "progress 100%"]
    assert "\x1b" not in out["output"]
    assert clean_output(b"a\r\nb\r") == "a\nb"


def test_long_output_keeps_head_and_tail_and_says_what_was_omitted(mgr):
    text, omitted = elide("H" * 30_000 + "T" * 30_000, 1000)
    assert omitted == 59_000 and text.startswith("H" * 500) and text.endswith("T" * 500) and "omitted" in text
    out = mgr.start("seq 1 40000", cwd=None, yield_s=10)
    assert out["omitted_chars"] > 0 and out["output"].splitlines()[0] == "1" and out["output"].rstrip().endswith("40000")


def test_the_number_of_live_sessions_is_bounded(mgr, monkeypatch):
    monkeypatch.setattr(pty_exec, "MAX_SESSIONS", 2)
    ids = [mgr.start("sleep 30", cwd=None, yield_s=0.1)["session_id"] for _ in range(2)]
    refused = mgr.start("sleep 30", cwd=None, yield_s=0.1)
    assert refused["ok"] is False and "too many" in refused["error"] and sorted(refused["sessions"]) == sorted(ids)


def test_a_missing_workdir_is_refused_not_started(mgr, tmp_path):
    out = mgr.start("echo x", cwd=str(tmp_path / "nope"), yield_s=1)
    assert out["ok"] is False and "workdir" in out["error"] and mgr.ids() == []


def test_the_command_runs_in_the_requested_workdir(mgr, tmp_path):
    out = mgr.start("pwd", cwd=str(tmp_path), yield_s=5)
    assert os.path.realpath(str(tmp_path)) in out["output"]


def test_cancelling_the_turn_returns_control_but_leaves_the_process_running(mgr):
    from jaeger_agent.util import tool_interrupt

    started = mgr.start("sleep 30", cwd=None, yield_s=0.2)
    tool_interrupt._interrupt.set()
    try:
        out = mgr.poll(started["session_id"], 30)
    finally:
        tool_interrupt.clear_interrupt()
    assert out.get("interrupted") is True and out["wall_time_s"] < 5
    assert mgr.get(started["session_id"]).running


def test_idle_sessions_are_reaped(mgr, monkeypatch):
    started = mgr.start("sleep 30", cwd=None, yield_s=0.1)
    mgr.get(started["session_id"]).last_used -= pty_exec.IDLE_TIMEOUT_S + 1
    mgr.start("true", cwd=None, yield_s=2)  # any start triggers the reaper
    assert mgr.ids() == []


# ── the gated tools an agent actually calls ────────────────────────────────

def test_tools_are_registered_and_classified():
    from jaeger_agent import tools  # noqa: F401
    from jaeger_agent.skill_registry.toolset_scoping import TOOLSETS

    assert {"exec_command", "write_stdin", "kill_command"} <= TOOLSETS["code"]


# ── the guarded entry points ────────────────────────────────────────────────
# The gated wrappers are what an agent calls. They must apply the same hardline
# and permission gates as ``terminal`` — including to keystrokes sent to a live
# process, which could otherwise smuggle a command past the start-time check.

from jaeger_os.core.safety.permissions import (  # noqa: E402
    AllowAllProvider,
    DenyAllProvider,
    PermissionDenied,
    PermissionPolicy,
    use_policy,
)


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    from jaeger_agent.workspace import DefaultWorkspace, bind

    bind(DefaultWorkspace(tmp_path / "agent").create())
    manager = PtyManager()
    monkeypatch.setattr(pty_exec, "_manager", manager)
    yield manager
    manager.kill_all()


def test_a_catastrophic_command_is_refused_before_anything_starts(guarded):
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = pty_exec.start_session(cmd="rm -rf /", workdir=None, yield_time_ms=100)
    assert out["hardline_blocked"] is True and guarded.ids() == []


def test_a_catastrophic_command_typed_into_a_live_shell_is_refused(guarded):
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        started = pty_exec.start_session(cmd="cat", workdir=None, yield_time_ms=200)
        out = pty_exec.type_into(chars="rm -rf /\n", session_id=started["session_id"], yield_time_ms=200)
    assert out["hardline_blocked"] is True
    # ...and nothing was written to the process.
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        assert "rm -rf" not in pty_exec._manager.poll(started["session_id"], 0.4)["output"]


def test_starting_a_command_needs_approval(guarded):
    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        with pytest.raises(PermissionDenied):
            pty_exec.start_session(cmd="echo hi", workdir=None, yield_time_ms=100)
    assert guarded.ids() == []


def test_polling_sends_nothing_and_needs_no_approval(guarded):
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        sid = pty_exec.start_session(cmd="sleep 0.5; echo done", workdir=None, yield_time_ms=50)["session_id"]
    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        out = pty_exec._t_write_stdin(session_id=sid, chars="", yield_time_ms=3000)
    assert "done" in out["output"] and out["exit_code"] == 0


def test_typing_needs_approval(guarded):
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        sid = pty_exec.start_session(cmd="cat", workdir=None, yield_time_ms=100)["session_id"]
    with use_policy(PermissionPolicy(confirmation=DenyAllProvider())):
        with pytest.raises(PermissionDenied):
            pty_exec._t_write_stdin(session_id=sid, chars="hello\n", yield_time_ms=300)
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        assert "hello" not in pty_exec._manager.poll(sid, 0.4)["output"]


def test_starts_are_audited(guarded, tmp_path):
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        pty_exec.start_session(cmd="echo audited-marker", workdir=None, yield_time_ms=500)
    logs = "".join(p.read_text(errors="ignore") for p in (tmp_path / "agent").rglob("*.jsonl")
                   ) + "".join(p.read_text(errors="ignore") for p in (tmp_path / "agent").rglob("*.log"))
    assert "exec_command" in logs and "audited-marker" in logs
