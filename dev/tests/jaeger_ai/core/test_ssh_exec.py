"""``ssh_exec`` — the agent-side remote-execution tool.

We can't run real SSH against a real host in a unit test (no fixtures,
no network), so the strategy is:

  - **argument construction**: pin the argv we hand to ``run_interruptible``
    via monkeypatch, so we know we built it correctly even when the
    binary never runs;
  - **host validation**: pin the rejects (empty, shell metachars,
    leading dash) without needing ssh on PATH;
  - **safety gates**: confirm the hardline guard and the tier-4 prompt
    both fire on the right inputs;
  - **end-to-end with a stub binary**: use ``echo`` (a guaranteed-present
    program) standing in as "ssh", so we exercise the subprocess path
    without an actual network.

What we DON'T test:
  - real SSH semantics (auth, key forwarding, ControlMaster)
  - audit-row contents (covered indirectly via ``_audit`` tests)
"""

from __future__ import annotations

import pytest

from jaeger_os.core.safety.permissions import (
    AllowAllProvider,
    PermissionPolicy,
    use_policy,
)
from jaeger_ai.agent.tools import remote as remote_tool
from jaeger_ai.agent.tools.remote import ssh_exec


# ── host validation (no SSH binary needed) ─────────────────────────


@pytest.mark.parametrize("bad_host", [
    "",                            # empty
    "   ",                         # whitespace-only
    "-oProxyCommand=evil",         # leading dash — would be parsed as a flag
    "host;rm -rf /",               # shell metachar
    "host && other",
    "host`whoami`",
    "host$(whoami)",
    'host"',
    "host\\",
])
def test_bad_hosts_are_rejected_with_a_useful_error(bad_host):
    """Inputs that could smuggle an ssh flag or shell escape must fail
    fast, *before* the subprocess is built. No tier prompt, no audit
    row, no command attempted."""
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = ssh_exec(host=bad_host, command="echo hi")
    assert out["ok"] is False
    assert "error" in out
    # ``exit_code`` is only populated when ssh actually ran.
    assert "exit_code" not in out


def test_empty_command_is_rejected():
    """An empty command would degenerate to ``ssh host ''`` — refuse it
    up front rather than producing a confusing remote no-op."""
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = ssh_exec(host="example.com", command="   ")
    assert out["ok"] is False
    assert out["error"] == "empty command"


# ── argv construction (monkeypatch the subprocess runner) ──────────


def test_argv_pins_safety_flags_and_uses_double_dash(monkeypatch):
    """The argv we hand to ssh has to:
      - force BatchMode (no password prompts),
      - cap connect time so a dead host fails fast,
      - use ``--`` so the remote command can begin with a dash,
      - place the destination BEFORE the command."""
    captured: dict = {}

    class FakeProc:
        stdout = "ok\n"
        stderr = ""
        returncode = 0

    def fake_runner(argv, **kw):
        captured["argv"] = argv
        captured["kw"] = kw
        return FakeProc()

    monkeypatch.setattr(remote_tool, "run_interruptible", fake_runner)

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = ssh_exec(host="user@example.com", command="uname -a", timeout_s=30)

    argv = captured["argv"]
    assert argv[0] == "ssh"
    # Required flags appear once, in the right shape.
    assert "BatchMode=yes" in argv
    assert "ConnectTimeout=10" in argv
    assert "StrictHostKeyChecking=accept-new" in argv
    # ``--`` separates ssh's flags from the destination + remote command.
    dd_idx = argv.index("--")
    assert argv[dd_idx + 1] == "user@example.com"
    assert argv[dd_idx + 2] == "uname -a"
    # Timeout we passed in routes to the subprocess runner.
    assert captured["kw"]["timeout"] == 30
    # Return shape carries through.
    assert out["ok"] is True
    assert out["host"] == "user@example.com"
    assert out["exit_code"] == 0
    assert "ok" in out["stdout"]


def test_timeout_is_clamped_to_a_sane_ceiling(monkeypatch):
    """A 9999-second timeout would let a wedged ssh hold the agent loop
    for almost three hours. We cap at 600s."""
    captured: dict = {}

    class FakeProc:
        stdout = ""; stderr = ""; returncode = 0

    monkeypatch.setattr(remote_tool, "run_interruptible",
                        lambda argv, **kw: (captured.update(kw), FakeProc())[1])
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        ssh_exec(host="example.com", command="true", timeout_s=9999)
    assert captured["timeout"] == 600.0


def test_timeout_zero_falls_back_to_default(monkeypatch):
    """``timeout_s=0`` is treated as 'unset' (same falsiness as ``None``)
    and uses the 60s default — matches ``run_shell``'s contract."""
    captured: dict = {}

    class FakeProc:
        stdout = ""; stderr = ""; returncode = 0

    monkeypatch.setattr(remote_tool, "run_interruptible",
                        lambda argv, **kw: (captured.update(kw), FakeProc())[1])
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        ssh_exec(host="example.com", command="true", timeout_s=0)
    assert captured["timeout"] == 60.0


def test_negative_timeout_floors_to_one_second(monkeypatch):
    """A literal negative is taken at face value (not falsy) and then
    clamped to the ``[1, 600]`` window — so a confused caller can't
    shave the timeout below where the subprocess runner can act."""
    captured: dict = {}

    class FakeProc:
        stdout = ""; stderr = ""; returncode = 0

    monkeypatch.setattr(remote_tool, "run_interruptible",
                        lambda argv, **kw: (captured.update(kw), FakeProc())[1])
    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        ssh_exec(host="example.com", command="true", timeout_s=-5)
    assert captured["timeout"] == 1.0


# ── failure modes ──────────────────────────────────────────────────


def test_missing_ssh_binary_returns_a_clear_error(monkeypatch):
    """If ``ssh`` isn't on PATH (CI runner, container without openssh),
    the user gets a one-line diagnosis rather than an opaque OSError."""
    def boom(argv, **kw):
        raise FileNotFoundError(2, "No such file or directory: 'ssh'")
    monkeypatch.setattr(remote_tool, "run_interruptible", boom)

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = ssh_exec(host="example.com", command="true")
    assert out["ok"] is False
    assert "ssh binary not found" in out["error"]


def test_interrupt_surfaces_with_exit_code_130(monkeypatch):
    """A user-cancelled turn kills the ssh child; we report it the same
    way ``run_shell`` does (exit 130, ``interrupted=True``) so callers
    can treat both uniformly."""
    from jaeger_ai.core.runtime.tool_interrupt import ToolInterrupted

    def boom(argv, **kw):
        raise ToolInterrupted(stdout=b"part", stderr=b"")
    monkeypatch.setattr(remote_tool, "run_interruptible", boom)

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = ssh_exec(host="example.com", command="sleep 9999")
    assert out["interrupted"] is True
    assert out["exit_code"] == 130
    assert out["stdout"] == "part"


# ── safety stack — both layers fire ────────────────────────────────


def test_hardline_blocks_a_catastrophic_remote_command():
    """``rm -rf /`` is catastrophic locally OR remotely. The hardline
    guard runs *before* the tier prompt so even an AllowAllProvider
    couldn't approve it."""
    out = ssh_exec(host="example.com", command="rm -rf /")
    assert out.get("hardline_blocked") is True
    assert out["ok"] is False
    # The function never reached the real implementation — no exit_code,
    # no audit, no ssh subprocess.
    assert "exit_code" not in out


def test_no_policy_installed_means_the_tier_gate_denies(monkeypatch):
    """Without an active permission policy + confirmation provider, a
    PRIVILEGED tool is refused — proven separately for ``ssh_exec`` so
    a future regression in the decorator stack would be caught here.

    ``install_policy()`` writes to BOTH a process-wide global AND the
    ``_current_policy`` contextvar without restoring on exit, so prior
    test modules can leave both set. We pin both to a fresh
    DenyAllProvider-by-default policy for the assertion."""
    from jaeger_os.core.safety import permissions as _perm

    monkeypatch.setattr(_perm, "_installed_policy", None)
    token = _perm._current_policy.set(_perm._DEFAULT_POLICY)
    try:
        with pytest.raises(_perm.PermissionDenied):
            ssh_exec(host="example.com", command="echo hi")
    finally:
        _perm._current_policy.reset(token)
