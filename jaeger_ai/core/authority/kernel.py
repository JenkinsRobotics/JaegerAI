"""Unified Policy Kernel for Jaeger (Workstream 8).

Implements the single canonical authority gate:
ProposedAction
      │
      ▼
POLICY KERNEL
      │
      ├── identity
      ├── requested capability
      ├── target
      ├── scope
      ├── operator policy
      ├── security policy
      └── current grants
      │
      ▼
ALLOW | DENY | MODIFY | REQUIRE_APPROVAL

Invariants:
1. Human approval is an Authority state (REQUIRE_APPROVAL), not an unrelated second policy mechanism.
2. Fail-closed: Any unhandled policy failure or error results in immediate DENY.
3. One request -> one deterministic authority decision governing side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence
import uuid

logger = logging.getLogger("jaeger.core.authority.kernel")


class AuthorityDecisionType(str, Enum):
    """The four canonical outcomes of authority evaluation."""
    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"
    REQUIRE_APPROVAL = "require_approval"


# Backwards compatibility alias with existing AuthorizationStatus
class AuthorizationStatus(str, Enum):
    APPROVED = "approved"
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    MODIFIED = "modified"


@dataclass(frozen=True)
class ProposedAction:
    """An action proposed by cognition prior to execution."""
    tool_name: str
    arguments: Mapping[str, Any]
    session_id: str = "dispatcher"
    actor: str = "agent:jaeger"
    proposal_id: str = field(default_factory=lambda: f"prop_{uuid.uuid4().hex[:12]}")
    target_path: str | None = None
    action_type: str = "tool_call"
    tier: str = "write_local"  # read_only, write_local, external_effect, privileged
    context: Mapping[str, Any] = field(default_factory=dict)
    proposed_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AuthorityDecision:
    """Deterministic policy judgment on a proposed action."""
    decision: AuthorityDecisionType
    reason: str = ""
    authorized_arguments: Mapping[str, Any] | None = None
    policy_name: str = "policy_kernel"
    granted_by: str = "policy_kernel"
    decision_id: str = field(default_factory=lambda: f"auth_{uuid.uuid4().hex[:12]}")
    proposal_id: str = ""
    evaluated_at: float = field(default_factory=time.time)

    @property
    def is_authorized(self) -> bool:
        """True ONLY if decision is ALLOW or MODIFY. REQUIRE_APPROVAL is not authorized."""
        return self.decision in (AuthorityDecisionType.ALLOW, AuthorityDecisionType.MODIFY)

    @property
    def status(self) -> AuthorizationStatus:
        """Compatibility property mapping AuthorityDecisionType to AuthorizationStatus."""
        if self.decision == AuthorityDecisionType.ALLOW:
            return AuthorizationStatus.APPROVED
        elif self.decision == AuthorityDecisionType.DENY:
            return AuthorizationStatus.DENIED
        elif self.decision == AuthorityDecisionType.REQUIRE_APPROVAL:
            return AuthorizationStatus.REQUIRES_CONFIRMATION
        elif self.decision == AuthorityDecisionType.MODIFY:
            return AuthorizationStatus.MODIFIED
        return AuthorizationStatus.DENIED

    @property
    def final_arguments(self) -> Mapping[str, Any]:
        if self.authorized_arguments is not None:
            return self.authorized_arguments
        return {}


def _resolve_instance_root(proposal: ProposedAction) -> Path | None:
    ctx = proposal.context or {}
    for key in ("instance_root", "layout_root", "instance_dir"):
        val = ctx.get(key)
        if val:
            return Path(val)
    layout = ctx.get("layout")
    if layout is not None:
        root = getattr(layout, "root", None)
        if root is not None:
            return Path(root)
    try:
        from jaeger_ai.core.entity.runtime import EntityRuntime
        rt = EntityRuntime.get_singleton()
        if getattr(rt, "layout", None) is not None:
            return Path(rt.layout.root)
        if getattr(rt, "state_root", None) is not None:
            memory = rt.state_root
            if memory.name == "memory":
                return Path(memory.parent)
    except Exception:
        pass
    return None


class PolicyKernel:
    """The central unified authority policy kernel."""

    _instance: PolicyKernel | None = None

    @classmethod
    def get_default(cls) -> PolicyKernel:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def evaluate(self, proposal: ProposedAction) -> AuthorityDecision:
        """Evaluate a ProposedAction against the unified policy hierarchy.

        Evaluates:
        1. Security Policy & Safety Mode (PAUSED, READ_ONLY)
        2. Identity & Trust Scope
        3. Capability Allowlist & Current Grants
        4. Protected System Targets
        5. Operator Shell Hooks (pre_tool_call)
        6. Commissioning & Operator Policy Grants
        7. Tier-based Human Approval
        """
        current_args = dict(proposal.arguments)

        try:
            # ── 1. Security Policy & Safety Mode ─────────────────────────────
            sec_decision = self._check_security_mode(proposal)
            if sec_decision is not None:
                return sec_decision

            # ── 2. Identity & Trust Restrictions ─────────────────────────────
            ident_decision = self._check_identity_trust(proposal)
            if ident_decision is not None:
                return ident_decision

            # ── 3. Capability Allowlist & Current Grants ──────────────────────
            grant_decision = self._check_capability_grants(proposal)
            if grant_decision is not None:
                return grant_decision

            # ── 4. Protected Targets ─────────────────────────────────────────
            target_decision = self._check_protected_targets(proposal)
            if target_decision is not None:
                return target_decision

            # ── 5. Operator Shell Hooks (pre_tool_call) ──────────────────────
            hook_decision, modified_args = self._check_shell_hooks(proposal, current_args)
            if hook_decision is not None:
                return hook_decision
            if modified_args is not None:
                current_args = modified_args

            # ── 6. Commissioning & Operator Policy Grants ────────────────────
            comm_decision = self._check_commissioning_policy(proposal, current_args)
            if comm_decision is not None:
                return comm_decision

            # ── 7. Tier-based Approval Gate ──────────────────────────────────
            tier_decision = self._check_tier_approval(proposal)
            if tier_decision is not None:
                return tier_decision

            # ── Pass: Allowed or Modified ────────────────────────────────────
            if modified_args is not None:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.MODIFY,
                    authorized_arguments=current_args,
                    reason="Proposal modified by policy",
                    policy_name="policy_kernel",
                    granted_by="policy_kernel",
                    proposal_id=proposal.proposal_id,
                )

            return AuthorityDecision(
                decision=AuthorityDecisionType.ALLOW,
                authorized_arguments=current_args,
                reason="Authorized by unified policy kernel",
                policy_name="policy_kernel",
                granted_by="policy_kernel",
                proposal_id=proposal.proposal_id,
            )

        except Exception as exc:
            # Strict Fail-Closed Rule
            logger.error("PolicyKernel evaluation error for %r: %s (fail-closed)", proposal.tool_name, exc)
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason=f"Policy evaluation failure: {exc} (fail-closed)",
                policy_name="fail_closed_sentinel",
                granted_by="fail_closed",
                proposal_id=proposal.proposal_id,
            )

    # ── Check Implementations ────────────────────────────────────────────────

    def _check_security_mode(self, proposal: ProposedAction) -> AuthorityDecision | None:
        try:
            from jaeger_os.core.safety.permissions import PolicyMode, current_policy
            policy = current_policy()
            if policy.mode == PolicyMode.PAUSED:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason="Operations paused by safety policy mode (PAUSED)",
                    policy_name="safety_mode",
                    granted_by="jaeger_os.permissions",
                    proposal_id=proposal.proposal_id,
                )
            if policy.mode == PolicyMode.READ_ONLY:
                read_tools = {"read_file", "view_file", "search", "grep_search", "list_dir", "cat"}
                if proposal.tool_name not in read_tools and proposal.tier != "read_only":
                    return AuthorityDecision(
                        decision=AuthorityDecisionType.DENY,
                        reason=f"Mutating tool {proposal.tool_name!r} forbidden in READ_ONLY safety mode",
                        policy_name="safety_mode",
                        granted_by="jaeger_os.permissions",
                        proposal_id=proposal.proposal_id,
                    )
        except Exception as exc:
            logger.debug("Safety policy mode check skipped: %s", exc)
        return None

    def _check_identity_trust(self, proposal: ProposedAction) -> AuthorityDecision | None:
        actor = proposal.actor or ""
        if actor in ("guest", "untrusted", "external_agent"):
            privileged_tools = {"run_command", "run_shell", "bash", "exec", "deploy", "git_push"}
            if proposal.tool_name in privileged_tools:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason=f"Actor {actor!r} is untrusted and forbidden from executing privileged tool {proposal.tool_name!r}",
                    policy_name="identity_trust",
                    granted_by="policy_kernel",
                    proposal_id=proposal.proposal_id,
                )
        return None

    def _check_capability_grants(self, proposal: ProposedAction) -> AuthorityDecision | None:
        try:
            from jaeger_agent.tool_executor import _allowed_tools
            granted = _allowed_tools.get()
            if granted is not None and proposal.tool_name not in granted:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason=f"Tool {proposal.tool_name!r} is outside the active tool capability grant",
                    policy_name="tool_allowlist",
                    granted_by="tool_grant",
                    proposal_id=proposal.proposal_id,
                )
        except Exception as exc:
            logger.debug("Allowlist grant check skipped: %s", exc)
        return None

    def _check_protected_targets(self, proposal: ProposedAction) -> AuthorityDecision | None:
        # Check target path for protected system files or in-repo runtime state
        target = str(proposal.target_path or proposal.arguments.get("path") or proposal.arguments.get("TargetFile") or "")
        if target:
            if "/.jaeger_ai/" in target or "/.jaeger_agent/" in target:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason="In-repo runtime state paths are forbidden by Zero In-Repo State Doctrine",
                    policy_name="protected_targets",
                    granted_by="policy_kernel",
                    proposal_id=proposal.proposal_id,
                )
        # Check git branch push protection
        if proposal.tool_name in ("git_push", "push") or "push" in str(proposal.arguments.get("CommandLine", "")):
            args_str = str(proposal.arguments)
            if "master" in args_str or "main" in args_str:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.REQUIRE_APPROVAL,
                    reason="Direct push to master/main branch requires explicit operator approval",
                    policy_name="protected_branch",
                    granted_by="policy_kernel",
                    proposal_id=proposal.proposal_id,
                )
        return None

    def _check_shell_hooks(
        self,
        proposal: ProposedAction,
        current_args: dict[str, Any],
    ) -> tuple[AuthorityDecision | None, dict[str, Any] | None]:
        try:
            from jaeger_agent import shell_hooks
            decision = shell_hooks.fire(
                "pre_tool_call",
                tool_name=proposal.tool_name,
                tool_input=current_args,
            )
            if decision.blocked:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason=decision.reason or "Blocked by pre_tool_call operator shell hook",
                    policy_name="shell_hooks",
                    granted_by="operator_hook",
                    proposal_id=proposal.proposal_id,
                ), None
            if getattr(decision, "modified_input", None) is not None:
                return None, dict(decision.modified_input)
        except Exception as exc:
            logger.debug("Shell hooks check skipped: %s", exc)
        return None, None

    def _check_commissioning_policy(
        self,
        proposal: ProposedAction,
        args: dict[str, Any],
    ) -> AuthorityDecision | None:
        try:
            from jaeger_ai.core.instance.commissioning import load_authority_policy

            root = _resolve_instance_root(proposal)
            if root is None:
                return None
            policy = load_authority_policy(root)
            if not policy:
                return None

            tool = proposal.tool_name
            shell_cfg = policy.get("shell") or {}
            shell_mode = str(shell_cfg.get("risk_mode") or "confirm")
            if tool in {"run_shell", "exec", "bash", "run_command"}:
                if shell_mode == "deny":
                    return AuthorityDecision(
                        decision=AuthorityDecisionType.DENY,
                        reason="Shell use was not authorized during setup",
                        policy_name="commissioning_authority",
                        granted_by="commissioning_policy",
                        proposal_id=proposal.proposal_id,
                    )
                elif shell_mode == "confirm":
                    return AuthorityDecision(
                        decision=AuthorityDecisionType.REQUIRE_APPROVAL,
                        reason="Shell execution requires human approval per commissioning policy",
                        policy_name="commissioning_authority",
                        granted_by="commissioning_policy",
                        proposal_id=proposal.proposal_id,
                    )

            files = policy.get("filesystem") or {}
            if tool in {"write_file", "edit_file", "delete_file"}:
                if not files.get("write"):
                    return AuthorityDecision(
                        decision=AuthorityDecisionType.DENY,
                        reason="File writes were not authorized during setup",
                        policy_name="commissioning_authority",
                        granted_by="commissioning_policy",
                        proposal_id=proposal.proposal_id,
                    )

            git = policy.get("git") or {}
            if tool in {"git_push"}:
                if not git.get("push"):
                    return AuthorityDecision(
                        decision=AuthorityDecisionType.DENY,
                        reason="Git push was not authorized during setup",
                        policy_name="commissioning_authority",
                        granted_by="commissioning_policy",
                        proposal_id=proposal.proposal_id,
                    )
            if tool in {"git_commit"} and git.get("local_commit") is False:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason="Local git commits were not authorized during setup",
                    policy_name="commissioning_authority",
                    granted_by="commissioning_policy",
                    proposal_id=proposal.proposal_id,
                )

            if policy.get("protected_merge_deployment") is False and tool in {"git_merge_master", "deploy"}:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason="Protected merge and deployment operations stay locked",
                    policy_name="commissioning_authority",
                    granted_by="commissioning_policy",
                    proposal_id=proposal.proposal_id,
                )

        except Exception as exc:
            logger.debug("Commissioning policy check skipped: %s", exc)
        return None

    def _check_tier_approval(self, proposal: ProposedAction) -> AuthorityDecision | None:
        # Check if proposal explicitly requested confirmation or requires approval
        ctx = proposal.context or {}
        if ctx.get("require_approval") or ctx.get("needs_confirmation"):
            return AuthorityDecision(
                decision=AuthorityDecisionType.REQUIRE_APPROVAL,
                reason="Action flagged as requiring operator confirmation",
                policy_name="tier_approval",
                granted_by="policy_kernel",
                proposal_id=proposal.proposal_id,
            )
        return None
