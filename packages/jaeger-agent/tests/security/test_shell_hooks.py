"""Operator shell hooks + the blocking pre_tool_call veto.

Ported from hermes-agent ``agent/shell_hooks.py``. The properties pinned here
are the ones that make an operator-supplied subprocess safe to run inside the
tool path: consent is required, a veto actually stops the call, only
pre_tool_call may veto, and a blocking hook that cannot answer is not read as
consent.
"""

from __future__ import annotations

import json
import os
import stat
from unittest import mock

import pytest

from jaeger_agent import shell_hooks as sh


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    from jaeger_ai.core.instance.instance import InstanceLayout

    layout = InstanceLayout(root=tmp_path)
    layout.root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("jaeger_agent.workspace.get_layout", lambda: layout)
    monkeypatch.setenv("JAEGER_SHELL_HOOKS", "1")
    monkeypatch.setenv("JAEGER_ACCEPT_HOOKS", "1")
    return layout


def _script(tmp_path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


def _hooks(monkeypatch, **events):
    """Point configured_hooks at an in-memory config."""
    def fake(event):
        return [sh.HookSpec(event=event, command=c)
                for c in events.get(event, [])]
    monkeypatch.setattr(sh, "configured_hooks", fake)


# ---------------------------------------------------------------------------
# Master switch
# ---------------------------------------------------------------------------

def test_disabled_by_default(instance, monkeypatch):
    monkeypatch.delenv("JAEGER_SHELL_HOOKS", raising=False)
    monkeypatch.setattr(sh, "_config", lambda: mock.Mock(hooks=None))
    assert sh.hooks_enabled() is False


def test_env_kill_switch_beats_config(instance, monkeypatch):
    """An operator must be able to boot past a hook that is itself broken."""
    monkeypatch.setenv("JAEGER_SHELL_HOOKS", "0")
    monkeypatch.setattr(
        sh, "_config", lambda: mock.Mock(hooks=mock.Mock(enabled=True)))
    assert sh.hooks_enabled() is False


def test_no_hooks_configured_is_a_clean_pass(instance, monkeypatch):
    _hooks(monkeypatch)
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is False


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def test_unapproved_hook_is_skipped(instance, tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_ACCEPT_HOOKS", raising=False)
    marker = tmp_path / "ran"
    cmd = _script(tmp_path, "h.sh", f"touch {marker}\nexit 2\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])

    # Not approved → not run, and therefore no block.
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is False
    assert not marker.exists()


def test_approved_hook_runs(instance, tmp_path, monkeypatch):
    monkeypatch.delenv("JAEGER_ACCEPT_HOOKS", raising=False)
    marker = tmp_path / "ran"
    cmd = _script(tmp_path, "h.sh", f"touch {marker}\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])
    sh.approve("pre_tool_call", cmd)

    sh.fire("pre_tool_call", tool_name="terminal")
    assert marker.exists()


def test_approval_is_per_event_and_command(instance, tmp_path):
    sh.approve("pre_tool_call", "/bin/true")
    assert sh.is_allowlisted("pre_tool_call", "/bin/true")
    assert not sh.is_allowlisted("post_tool_call", "/bin/true")
    assert not sh.is_allowlisted("pre_tool_call", "/bin/false")


def test_revoke(instance):
    sh.approve("pre_tool_call", "/bin/true")
    sh.approve("post_tool_call", "/bin/true")
    assert sh.revoke("/bin/true") == 2
    assert not sh.is_allowlisted("pre_tool_call", "/bin/true")


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

def test_exit_2_blocks(instance, tmp_path, monkeypatch):
    cmd = _script(tmp_path, "deny.sh", "exit 2\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])
    d = sh.fire("pre_tool_call", tool_name="terminal")
    assert d.blocked is True


def test_json_decision_blocks_with_reason(instance, tmp_path, monkeypatch):
    cmd = _script(
        tmp_path, "deny.sh",
        'echo \'{"decision":"block","reason":"deploy freeze"}\'\n')
    _hooks(monkeypatch, pre_tool_call=[cmd])
    d = sh.fire("pre_tool_call", tool_name="write_file")
    assert d.blocked is True
    assert d.reason == "deploy freeze"


def test_exit_0_allows(instance, tmp_path, monkeypatch):
    cmd = _script(tmp_path, "ok.sh", "exit 0\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is False


def test_nonzero_but_not_2_allows(instance, tmp_path, monkeypatch):
    """Only exit 2 is a veto; a crashing hook is not a policy decision."""
    cmd = _script(tmp_path, "broken.sh", "exit 1\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is False


def test_post_tool_call_cannot_block(instance, tmp_path, monkeypatch):
    """The side effect already happened — a block there would be a lie."""
    cmd = _script(tmp_path, "deny.sh", "exit 2\n")
    _hooks(monkeypatch, post_tool_call=[cmd])
    assert sh.fire("post_tool_call", tool_name="terminal").blocked is False


def test_timeout_on_a_blocking_hook_denies(instance, tmp_path, monkeypatch):
    """A gate that cannot answer must not be read as consent."""
    cmd = _script(tmp_path, "slow.sh", "sleep 5\n")
    monkeypatch.setattr(
        sh, "configured_hooks",
        lambda e: [sh.HookSpec(event=e, command=cmd, timeout=1)]
        if e == "pre_tool_call" else [])
    d = sh.fire("pre_tool_call", tool_name="terminal")
    assert d.blocked is True
    assert "timed out" in d.reason


def test_timeout_on_a_nonblocking_hook_allows(instance, tmp_path, monkeypatch):
    cmd = _script(tmp_path, "slow.sh", "sleep 5\n")
    monkeypatch.setattr(
        sh, "configured_hooks",
        lambda e: [sh.HookSpec(event=e, command=cmd, timeout=1)]
        if e == "post_tool_call" else [])
    assert sh.fire("post_tool_call", tool_name="terminal").blocked is False


def test_missing_binary_on_a_blocking_hook_denies(instance, monkeypatch):
    _hooks(monkeypatch, pre_tool_call=["/definitely/not/here"])
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is True


def test_first_block_short_circuits(instance, tmp_path, monkeypatch):
    later = tmp_path / "later"
    deny = _script(tmp_path, "deny.sh", "exit 2\n")
    after = _script(tmp_path, "after.sh", f"touch {later}\n")
    _hooks(monkeypatch, pre_tool_call=[deny, after])
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is True
    assert not later.exists()


# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------

def test_payload_reaches_the_hook_on_stdin(instance, tmp_path, monkeypatch):
    out = tmp_path / "payload.json"
    cmd = _script(tmp_path, "cap.sh", f"cat > {out}\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])

    sh.fire("pre_tool_call", tool_name="terminal",
            tool_input={"command": "rm -rf /"})
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["hook_event_name"] == "pre_tool_call"
    assert got["tool_name"] == "terminal"
    assert got["tool_input"] == {"command": "rm -rf /"}


def test_no_shell_is_used(instance, tmp_path, monkeypatch):
    """shell=False, so a metacharacter in the command is not interpreted."""
    pwned = tmp_path / "pwned"
    _hooks(monkeypatch, pre_tool_call=[f"/bin/echo hi; touch {pwned}"])
    sh.fire("pre_tool_call", tool_name="terminal")
    assert not pwned.exists()


def test_free_form_stdout_is_ignored(instance, tmp_path, monkeypatch):
    cmd = _script(tmp_path, "chatty.sh", "echo just logging\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is False


def test_tool_filter(instance, tmp_path, monkeypatch):
    cmd = _script(tmp_path, "deny.sh", "exit 2\n")
    monkeypatch.setattr(
        sh, "configured_hooks",
        lambda e: [sh.HookSpec(event=e, command=cmd, tools=("write_file",))]
        if e == "pre_tool_call" else [])
    assert sh.fire("pre_tool_call", tool_name="terminal").blocked is False
    assert sh.fire("pre_tool_call", tool_name="write_file").blocked is True


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------

def test_hooked_executor_blocks_the_call(instance, tmp_path, monkeypatch):
    from jaeger_agent.tool_executor import HookedToolExecutor

    cmd = _script(tmp_path, "deny.sh", "exit 2\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])

    inner = mock.Mock()
    inner.execute.return_value = {"ok": True}
    tool = mock.Mock()
    tool.name = "terminal"

    out = HookedToolExecutor(inner).execute(tool, {"command": "ls"})
    assert out["ok"] is False
    assert out["error_type"] == "blocked_by_hook"
    assert out["retryable"] is False
    inner.execute.assert_not_called()


def test_hooked_executor_passes_through_when_allowed(instance, monkeypatch):
    from jaeger_agent.tool_executor import HookedToolExecutor

    _hooks(monkeypatch)
    inner = mock.Mock()
    inner.execute.return_value = {"ok": True, "value": 42}
    tool = mock.Mock()
    tool.name = "get_time"

    out = HookedToolExecutor(inner).execute(tool, {})
    assert out == {"ok": True, "value": 42}
    inner.execute.assert_called_once()


def test_a_blocked_call_never_reaches_the_ledger(instance, tmp_path, monkeypatch):
    """Composition order matters: a veto must not burn the effect key."""
    from jaeger_agent.tool_executor import HookedToolExecutor

    cmd = _script(tmp_path, "deny.sh", "exit 2\n")
    _hooks(monkeypatch, pre_tool_call=[cmd])

    ledger = mock.Mock()
    tool = mock.Mock()
    tool.name = "send_email"
    tool.side_effect = "external"

    HookedToolExecutor(ledger).execute(tool, {"to": "x@y.z"})
    ledger.execute.assert_not_called()
