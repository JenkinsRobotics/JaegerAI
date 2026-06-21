"""Hardline command blocklist — the unconditional floor under run_shell.

Audit A9. `run_shell` is tier-4 (a human approves every command), but the
tier prompt never inspects what the command actually *does*.
`core/command_guard.py` refuses a short list of catastrophic,
no-legitimate-use commands outright — below even the tier prompt.

The guard is deliberately conservative: a false positive (blocking a
real command) is worse than a miss (the human still sees the prompt), so
the allow-list cases below are as load-bearing as the block cases.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.safety.command_guard import check_hardline, hardline_guard


# ── blocked: catastrophic, zero legitimate use ──────────────────────


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf /*",
    "rm -fr /",
    "rm -Rf /",
    "rm -r -f /",
    "rm --recursive --force /",
    "rm -rf ~",
    "rm -rf $HOME",
    "sudo rm -rf /usr",
    "rm -rf /etc",
    "rm -rf /etc/*",
    'rm -rf "/"',                       # quote evasion
    "cd /tmp && sudo rm -rf /",         # in command position after &&
    "mkfs.ext4 /dev/sda1",
    "mkfs /dev/disk2",
    "dd if=/dev/zero of=/dev/disk0",
    "dd if=backup.img of=/dev/sda bs=4M",
    "echo boom > /dev/sda",
    ":(){ :|:& };:",                    # fork bomb
    "shutdown -h now",
    "sudo reboot",
    "poweroff",
    "halt",
])
def test_hardline_blocks_catastrophic(cmd):
    assert check_hardline(cmd) is not None, cmd


# ── allowed: legitimate, must NOT be blocked ────────────────────────


@pytest.mark.parametrize("cmd", [
    "rm -rf ./build",
    "rm -rf node_modules",
    "rm -rf /tmp/jaeger-scratch",
    "rm -rf /usr/local/share/myapp/cache",   # deep subpath, not top-level
    "rm file.txt",
    "rm -r somedir",                          # recursive but a local target
    "ls /etc",
    "cat /etc/hosts",
    "cat /etc/hosts && rm -rf ./tmpdir",      # /etc is in the unrelated cat
    'echo "rm -rf /"',                        # rm is quoted text, not a command
    "echo shutdown the build pipeline",       # shutdown is an argument
    "git reset --hard HEAD~1",
    "dd if=/dev/zero of=/dev/null count=1",   # /dev/null is harmless
    "dd if=a.img of=b.img",
    "python -c 'print(1)'",
    "",
    "   ",
])
def test_hardline_allows_legitimate(cmd):
    assert check_hardline(cmd) is None, cmd


# ── the hardline_guard decorator ────────────────────────────────────


def test_guard_blocks_and_returns_a_structured_result():
    @hardline_guard("command")
    def fake(command: str) -> dict:
        return {"ran": True}

    out = fake(command="rm -rf /")
    assert out["hardline_blocked"] is True
    assert out["ok"] is False
    assert "ran" not in out          # the wrapped function never ran


def test_guard_passes_a_safe_command_through():
    @hardline_guard("command")
    def fake(command: str) -> dict:
        return {"ran": True, "command": command}

    assert fake(command="echo hello") == {"ran": True, "command": "echo hello"}


# ── run_shell integration ───────────────────────────────────────────


def test_run_shell_blocks_a_hardline_command_below_the_tier_prompt():
    """The guard is applied OUTSIDE @requires_tier — a catastrophic
    command is refused with no policy installed and no prompt shown: the
    tier-gated body is never reached."""
    from jaeger_os.agent.tools.code import run_shell

    out = run_shell(command="rm -rf /")
    assert out["hardline_blocked"] is True
    assert out["ok"] is False
    assert "exit_code" not in out     # never reached the real implementation


def test_run_shell_lets_a_safe_command_reach_the_tier_layer():
    """A safe command is not hardline-blocked — it proceeds to the tier
    check (approved here) and runs normally."""
    from jaeger_os.core.safety.permissions import (
        AllowAllProvider,
        PermissionPolicy,
        use_policy,
    )
    from jaeger_os.agent.tools.code import run_shell

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        out = run_shell(command="echo hello", timeout_s=10)
    assert out.get("hardline_blocked") is None   # not blocked
    assert out["ok"] is True
    assert "hello" in out["stdout"]
