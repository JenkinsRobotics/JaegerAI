"""Destructive / irreversible actions need a fresh owner approval.

System-engineer decision 2026-10-09 (SOTA POL-01: a standing "always" shell
grant let ``rm -rf`` run with no prompt). Non-overridable PolicyKernel rule.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_ai.core.authority.destructive import destructive_reason
from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction

DESTRUCTIVE = [
    ("terminal", {"command": "rm -rf /Users/x/workspace/old_logs"}),
    ("bash", {"command": "cd /x && /bin/rm -r -f logs"}),
    ("run_shell", {"command": "sudo \\rm -fr dir"}),
    ("exec", {"command": "bash -c 'rm -rf x; ls'"}),
    ("mcp__jaeger__terminal", {"command": "echo ok\nrm -rf x"}),
    ("Functions.Bash", {"command": 'echo "$(rm -rf ~/x)"'}),
    ("execute_command", {"command": "env A=1 nohup timeout 5 rm -rf a"}),
    ("terminal", {"command": "ls | xargs rm"}),
    ("terminal", {"command": "find . -name '*.log' -delete"}),
    ("terminal", {"command": "git reset --hard HEAD~1"}),
    ("terminal", {"command": "git -C repo push --force origin main"}),
    ("terminal", {"command": "git push origin +main"}),
    ("terminal", {"command": "git clean -fdx"}),
    ("terminal", {"command": "git branch -D topic"}),
    ("terminal", {"command": "git checkout -- ."}),
    ("terminal", {"command": "sqlite3 app.db 'DROP TABLE users'"}),
    ("terminal", {"command": "dropdb prod"}),
    ("terminal", {"command": "dd if=/dev/zero of=/dev/disk2"}),
    ("terminal", {"command": "rm notes.txt"}),
    ("ssh", {"command": "rm -rf /srv/data"}),
    ("delete_file", {"path": "workspace/x/state/job.lock"}),
    ("execute_code", {"code": "import shutil; shutil.rmtree('data')"}),
    ("run_python", {"code": "import os\nos.remove('a')"}),
    ("git_push", {"force": True}),
    ("drop_table", {"name": "users"}),
]

SAFE = [
    ("terminal", {"command": "ls -la && git status"}),
    ("terminal", {"command": "timeout 10 bash run.sh"}),
    ("terminal", {"command": "grep -rn 'rm -rf' docs"}),
    ("terminal", {"command": "git push origin feature"}),
    ("terminal", {"command": "git restore --staged a.py"}),
    ("terminal", {"command": "python3 -c 'print(1)' 2>&1 | tail -1"}),
    ("terminal", {"command": "rm /tmp/jaeger_scratch_x/out.txt"}),
    ("delete_file", {"path": "/tmp/jaeger_scratch_x/out.txt"}),
    ("execute_code", {"code": "print(sum([1, 2]))"}),
    ("read_file", {"path": "workspace/a.txt"}),
]


@pytest.mark.parametrize("tool,args", DESTRUCTIVE)
def test_destructive_calls_are_detected_under_every_alias(tool, args):
    assert destructive_reason(tool, args)


@pytest.mark.parametrize("tool,args", SAFE)
def test_ordinary_calls_are_not_flagged(tool, args):
    assert destructive_reason(tool, args) is None


def _evaluate(tool, args):
    return PolicyKernel().evaluate(ProposedAction(tool_name=tool, arguments=args, actor="owner:test"))


@pytest.mark.parametrize("tool,args", DESTRUCTIVE[:6])
def test_kernel_requires_approval_for_destructive_calls(tool, args):
    decision = _evaluate(tool, args)
    assert decision.decision == AuthorityDecisionType.REQUIRE_APPROVAL
    assert decision.policy_name == "destructive_action"
    assert not decision.is_authorized


def test_kernel_does_not_flag_ordinary_shell_use():
    assert _evaluate("terminal", {"command": "ls -la"}).policy_name != "destructive_action"


def test_a_hook_rewrite_into_a_destructive_call_is_judged_again(monkeypatch):
    from jaeger_agent import shell_hooks

    rewrite = SimpleNamespace(blocked=False, reason="", modified_input={"command": "rm -rf /data"})
    monkeypatch.setattr(shell_hooks, "fire", lambda *a, **k: rewrite)
    decision = _evaluate("terminal", {"command": "ls"})
    assert decision.decision == AuthorityDecisionType.REQUIRE_APPROVAL
    assert decision.policy_name == "destructive_action"


def test_detection_failure_fails_closed(monkeypatch):
    import jaeger_ai.core.authority.destructive as mod

    def boom(*a, **k):
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(mod, "destructive_reason", boom)
    assert _evaluate("terminal", {"command": "ls"}).decision == AuthorityDecisionType.DENY


def test_executor_refuses_a_provider_that_cannot_ask_fresh():
    """AllowAll (--yes), bench and commissioning providers approve without a
    human; they cannot answer a destructive-action approval."""
    from jaeger_agent.tool_executor import _owner_approves
    from jaeger_os.core.safety.permissions import AllowAllProvider, PermissionPolicy, use_policy

    with use_policy(PermissionPolicy(confirmation=AllowAllProvider())):
        assert _owner_approves("terminal", {"command": "rm -rf x"}, "destructive") is False


def test_executor_asks_a_fresh_provider_with_force_prompt():
    from jaeger_agent.tool_executor import _owner_approves
    from jaeger_os.core.safety.permissions import PermissionPolicy, use_policy

    seen = []

    class Human:
        fresh_approval = True

        def confirm(self, request):
            seen.append(request)
            return True

    with use_policy(PermissionPolicy(confirmation=Human())):
        assert _owner_approves("terminal", {"command": "rm -rf x"}, "destructive") is True
    assert seen and seen[0].force_prompt is True


def test_console_provider_ignores_a_standing_grant_for_a_fresh_request(tmp_path, monkeypatch):
    from jaeger_os.core.safety.permissions import ConsoleConfirmationProvider, PermissionTier

    provider = ConsoleConfirmationProvider(tmp_path)
    provider._grants.grant_persistent("policy:terminal")
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    req = SimpleNamespace(skill="policy:terminal", operation="terminal", tier=PermissionTier.PRIVILEGED,
                          summary="rm -rf", force_prompt=False)
    assert provider.confirm(req) is True          # ordinary request: the grant applies
    req.force_prompt = True
    assert provider.confirm(req) is False         # fresh request: no human here -> refused


def test_bus_provider_does_not_auto_approve_a_fresh_request(monkeypatch):
    from jaeger_agent.loop.bus_confirm import BusConfirmationProvider
    from jaeger_ai.core.runtime import autonomy
    from jaeger_os.core.safety import session_trust

    published = []
    bus = SimpleNamespace(subscribe=lambda *a: None, publish=published.append)
    provider = BusConfirmationProvider(bus, timeout_s=0.05)
    provider._granted_skills.add("policy:terminal")
    monkeypatch.setattr(session_trust, "is_admin_session", lambda s: True)
    monkeypatch.setattr(autonomy, "current_autonomy", lambda: "auto")
    req = SimpleNamespace(skill="policy:terminal", operation="terminal", summary="rm -rf", force_prompt=True)
    assert provider.confirm(req) is False         # asked (no answer) instead of auto/grant
    assert published and "always" not in published[0].options
