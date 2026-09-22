"""Tests for the Unified Policy / Capability / Authority System (Workstream 8).

Verifies Authority Invariants:
1. ProposedAction -> PolicyKernel -> ALLOW | DENY | MODIFY | REQUIRE_APPROVAL
2. Human approval is an Authority state (REQUIRE_APPROVAL), not an unrelated second policy mechanism.
3. Strict Fail-Closed: any unhandled exception or policy error immediately DENIES.
4. Active capability grants (allowlist) are strictly enforced.
5. Untrusted actors cannot invoke privileged tools.
6. Safety mode (PAUSED / READ_ONLY) halts execution.
"""
from pathlib import Path
import pytest

from jaeger_ai.core.authority.kernel import (
    AuthorityDecision,
    AuthorityDecisionType,
    AuthorizationStatus,
    PolicyKernel,
    ProposedAction,
)
from jaeger_ai.core.entity.authority import AuthorityLayer, ProposedAction as LayerProposedAction


@pytest.fixture
def kernel():
    return PolicyKernel()


def test_allow_safe_read_action(kernel: PolicyKernel):
    """A standard safe read tool by default agent actor is allowed."""
    prop = ProposedAction(
        tool_name="read_file",
        arguments={"path": "README.md"},
        actor="agent:jaeger",
    )
    decision = kernel.evaluate(prop)
    assert decision.decision == AuthorityDecisionType.ALLOW
    assert decision.is_authorized is True
    assert decision.status == AuthorizationStatus.APPROVED


def test_deny_untrusted_actor_privileged_tool(kernel: PolicyKernel):
    """Untrusted actor (e.g. guest or external) cannot run privileged commands."""
    prop = ProposedAction(
        tool_name="run_command",
        arguments={"CommandLine": "rm -rf /tmp"},
        actor="guest",
    )
    decision = kernel.evaluate(prop)
    assert decision.decision == AuthorityDecisionType.DENY
    assert decision.is_authorized is False
    assert decision.status == AuthorizationStatus.DENIED
    assert "untrusted" in decision.reason


def test_require_approval_protected_branch_push(kernel: PolicyKernel):
    """Direct push targeting master requires human approval as an Authority state."""
    prop = ProposedAction(
        tool_name="git_push",
        arguments={"remote": "origin", "branch": "master"},
        actor="agent:jaeger",
    )
    decision = kernel.evaluate(prop)
    assert decision.decision == AuthorityDecisionType.REQUIRE_APPROVAL
    assert decision.is_authorized is False
    assert decision.status == AuthorizationStatus.REQUIRES_CONFIRMATION
    assert "master" in decision.reason


def test_deny_when_safety_mode_paused(kernel: PolicyKernel, monkeypatch: pytest.MonkeyPatch):
    """When jaeger_os safety policy is PAUSED, all actions are denied."""
    try:
        from jaeger_os.core.safety.permissions import PermissionPolicy, PolicyMode, install_policy
        install_policy(PermissionPolicy(mode=PolicyMode.PAUSED))

        prop = ProposedAction(
            tool_name="read_file",
            arguments={"path": "notes.txt"},
        )
        decision = kernel.evaluate(prop)
        assert decision.decision == AuthorityDecisionType.DENY
        assert decision.is_authorized is False
        assert "PAUSED" in decision.reason
    finally:
        # Reset policy
        from jaeger_os.core.safety.permissions import PermissionPolicy, PolicyMode, install_policy
        install_policy(PermissionPolicy(mode=PolicyMode.NORMAL))


def test_capability_grant_allowlist_enforced(kernel: PolicyKernel):
    """When an active tool allowlist is set, tools outside the grant are denied."""
    from jaeger_agent.tool_executor import tool_allowlist

    with tool_allowlist(["read_file", "search"]):
        # read_file is in the grant
        prop_allowed = ProposedAction(
            tool_name="read_file",
            arguments={"path": "test.txt"},
        )
        dec_allowed = kernel.evaluate(prop_allowed)
        assert dec_allowed.decision == AuthorityDecisionType.ALLOW

        # run_command is not in the grant
        prop_denied = ProposedAction(
            tool_name="run_command",
            arguments={"CommandLine": "echo hello"},
        )
        dec_denied = kernel.evaluate(prop_denied)
        assert dec_denied.decision == AuthorityDecisionType.DENY
        assert "outside the active tool capability grant" in dec_denied.reason


def test_fail_closed_sentinel(kernel: PolicyKernel, monkeypatch: pytest.MonkeyPatch):
    """Any unhandled crash in policy evaluation fails closed (DENY)."""
    monkeypatch.setattr(
        kernel,
        "_check_security_mode",
        lambda prop: (_ for _ in ()).throw(RuntimeError("Unexpected kernel crash")),
    )
    prop = ProposedAction(
        tool_name="read_file",
        arguments={"path": "test.txt"},
    )
    decision = kernel.evaluate(prop)
    assert decision.decision == AuthorityDecisionType.DENY
    assert decision.is_authorized is False
    assert "fail-closed" in decision.reason


def test_authority_layer_integration():
    """AuthorityLayer seamlessly evaluates through PolicyKernel."""
    layer = AuthorityLayer()
    prop = LayerProposedAction(
        tool_name="run_command",
        arguments={"CommandLine": "cat /etc/passwd"},
        actor="guest",
    )
    decision = layer.authorize(prop)
    assert decision.is_authorized is False
    assert decision.status == AuthorizationStatus.DENIED
    assert "untrusted" in decision.reason
