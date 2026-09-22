"""Authority and Policy Boundary Contract (UPAA Principle 14 & Invariant 6).

Core Invariant:
    COGNITION PROPOSES ACTION
    ──► AUTHORITY LAYER AUTHORIZES/DENIES
    ──► ACTION SYSTEM / EXECUTOR EXECUTES
    ──► ENVIRONMENT PRODUCES CONSEQUENCE
    ──► CONSEQUENCE EVENT
    ──► INDEPENDENT VERIFICATION

No action executor may perform an externally meaningful action before
deterministic authorization has completed. The executor must never get an
unapproved action and then ask policy afterward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Callable, Mapping

logger = logging.getLogger("jaeger.entity.authority")


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
    proposed_at: float = field(default_factory=time.time)
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthorityDecision:
    """Deterministic policy judgment on a proposed action."""

    status: AuthorizationStatus
    reason: str = ""
    authorized_arguments: Mapping[str, Any] | None = None
    policy_name: str = "default_policy"
    evaluated_at: float = field(default_factory=time.time)

    @property
    def is_authorized(self) -> bool:
        return self.status in (AuthorizationStatus.APPROVED, AuthorizationStatus.MODIFIED)

    @property
    def final_arguments(self) -> Mapping[str, Any]:
        if self.authorized_arguments is not None:
            return self.authorized_arguments
        return {}


PolicyCheckFn = Callable[[ProposedAction], AuthorityDecision]


def default_shell_hooks_policy(proposal: ProposedAction) -> AuthorityDecision:
    """Evaluate pre_tool_call shell hooks."""
    try:
        from jaeger_agent import shell_hooks

        decision = shell_hooks.fire(
            "pre_tool_call",
            tool_name=proposal.tool_name,
            tool_input=dict(proposal.arguments),
        )
        if decision.blocked:
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason=decision.reason or "blocked by pre_tool_call hook",
                policy_name="shell_hooks",
            )
    except Exception as exc:
        logger.debug("Shell hooks policy check skipped: %s", exc)
    return AuthorityDecision(status=AuthorizationStatus.APPROVED, policy_name="shell_hooks")


def default_allowlist_policy(proposal: ProposedAction) -> AuthorityDecision:
    """Evaluate current tool allowlist grant."""
    try:
        from jaeger_agent.tool_executor import _allowed_tools

        granted = _allowed_tools.get()
        if granted is not None and proposal.tool_name not in granted:
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason=f"Tool {proposal.tool_name!r} is outside the allowed toolset",
                policy_name="tool_allowlist",
            )
    except Exception as exc:
        logger.debug("Allowlist policy check skipped: %s", exc)
    return AuthorityDecision(status=AuthorizationStatus.APPROVED, policy_name="tool_allowlist")


def default_permissions_policy(proposal: ProposedAction) -> AuthorityDecision:
    """Evaluate safety permission mode (e.g. PAUSED)."""
    try:
        from jaeger_os.core.safety.permissions import PolicyMode, current_policy

        policy = current_policy()
        if policy.mode == PolicyMode.PAUSED:
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="Operations paused by safety policy",
                policy_name="permission_mode",
            )
    except Exception as exc:
        logger.debug("Permission policy check skipped: %s", exc)
    return AuthorityDecision(status=AuthorizationStatus.APPROVED, policy_name="permission_mode")


def _authority_instance_root(proposal: ProposedAction) -> Any:
    """Resolve the instance that owns this proposal — never a global default."""
    ctx = proposal.context or {}
    for key in ("instance_root", "layout_root", "instance_dir"):
        val = ctx.get(key)
        if val:
            return val
    layout = ctx.get("layout")
    if layout is not None:
        root = getattr(layout, "root", None)
        if root is not None:
            return root
    try:
        from jaeger_ai.core.entity.runtime import EntityRuntime
        rt = EntityRuntime.get_singleton()
        if getattr(rt, "layout", None) is not None:
            return rt.layout.root
        if getattr(rt, "state_root", None) is not None:
            # state_root is instance memory/; policy lives on the instance root
            memory = rt.state_root
            if memory.name == "memory":
                return memory.parent
    except Exception:
        pass
    return None


def commissioning_authority_policy(proposal: ProposedAction) -> AuthorityDecision:
    """Capability-scoped policy written during commissioning.

    Human answers become this document. Missing policy fails open to the
    existing confirm/allow posture so established instances keep working.
    The policy is always the instance bound to this runtime/proposal.
    """
    try:
        from jaeger_ai.core.instance.commissioning import load_authority_policy

        root = _authority_instance_root(proposal)
        if root is None:
            return AuthorityDecision(
                status=AuthorizationStatus.APPROVED,
                policy_name="commissioning_authority",
                reason="no instance bound; policy not applied",
            )
        policy = load_authority_policy(root)
        if not policy:
            return AuthorityDecision(status=AuthorizationStatus.APPROVED, policy_name="commissioning_authority")
        tool = proposal.tool_name
        shell_mode = str((policy.get("shell") or {}).get("risk_mode") or "confirm")
        if tool in {"run_shell", "exec", "bash", "run_command"} and shell_mode == "deny":
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="Shell use was not authorized during setup",
                policy_name="commissioning_authority",
            )
        files = policy.get("filesystem") or {}
        if tool in {"write_file", "edit_file", "delete_file"} and not files.get("write"):
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="File writes were not authorized during setup",
                policy_name="commissioning_authority",
            )
        git = policy.get("git") or {}
        if tool in {"git_push"} and not git.get("push"):
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="Git push was not authorized during setup",
                policy_name="commissioning_authority",
            )
        if tool in {"git_commit"} and git.get("local_commit") is False:
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="Local git commits were not authorized during setup",
                policy_name="commissioning_authority",
            )
        if policy.get("protected_merge_deployment") is False and tool in {"git_merge_master", "deploy"}:
            return AuthorityDecision(
                status=AuthorizationStatus.DENIED,
                reason="Protected merge and deployment operations stay locked",
                policy_name="commissioning_authority",
            )
    except Exception as exc:
        logger.debug("Commissioning authority policy skipped: %s", exc)
    return AuthorityDecision(status=AuthorizationStatus.APPROVED, policy_name="commissioning_authority")


from ..authority import AuthorityDecisionType, PolicyKernel


class AuthorityLayer:
    """The canonical authority boundary guarding the action system.
    
    Guarantees that no proposed action reaches the environment without
    prior evaluation against registered policy rules and operator hooks.
    """

    def __init__(
        self,
        policies: list[PolicyCheckFn] | None = None,
        kernel: PolicyKernel | None = None,
    ) -> None:
        self.kernel = kernel or PolicyKernel.get_default()
        self._policies: list[PolicyCheckFn] = list(policies) if policies is not None else [
            default_shell_hooks_policy,
            default_allowlist_policy,
            default_permissions_policy,
            commissioning_authority_policy,
        ]

    def register_policy(self, policy: PolicyCheckFn) -> None:
        self._policies.append(policy)

    def authorize(self, proposal: ProposedAction) -> AuthorityDecision:
        """Evaluate the proposed action against PolicyKernel and registered policies.
        
        First denial or confirmation gate immediately blocks dispatch.
        """
        # 1. Canonical PolicyKernel check
        from ..authority import ProposedAction as KernelProposal
        k_proposal = KernelProposal(
            tool_name=proposal.tool_name,
            arguments=proposal.arguments,
            session_id=proposal.session_id,
            actor=proposal.actor,
            context=proposal.context,
            proposed_at=proposal.proposed_at,
        )
        kernel_decision = self.kernel.evaluate(k_proposal)
        if not kernel_decision.is_authorized:
            logger.warning(
                "Proposed action %r blocked by PolicyKernel (%s): %s",
                proposal.tool_name,
                kernel_decision.policy_name,
                kernel_decision.reason,
            )
            return AuthorityDecision(
                status=kernel_decision.status,
                reason=kernel_decision.reason,
                authorized_arguments=kernel_decision.authorized_arguments,
                policy_name=kernel_decision.policy_name,
            )

        # 2. Registered policies
        current_args = kernel_decision.authorized_arguments if kernel_decision.authorized_arguments is not None else proposal.arguments

        for policy in self._policies:
            try:
                decision = policy(proposal)
                if not decision.is_authorized:
                    logger.warning(
                        "Proposed action %r blocked by policy %r: %s",
                        proposal.tool_name,
                        decision.policy_name,
                        decision.reason,
                    )
                    return decision
                if decision.authorized_arguments is not None:
                    current_args = decision.authorized_arguments
                    proposal = ProposedAction(
                        tool_name=proposal.tool_name,
                        arguments=current_args,
                        session_id=proposal.session_id,
                        actor=proposal.actor,
                        proposed_at=proposal.proposed_at,
                        context=proposal.context,
                    )
            except Exception as exc:
                logger.error(
                    "Policy %r failed evaluation for %r: %s (fail-closed)",
                    getattr(policy, "__name__", "unknown"),
                    proposal.tool_name,
                    exc,
                )
                return AuthorityDecision(
                    status=AuthorizationStatus.DENIED,
                    reason=f"Policy evaluation error: {exc} (fail-closed)",
                    policy_name=getattr(policy, "__name__", "fail_closed"),
                )

        return AuthorityDecision(
            status=AuthorizationStatus.APPROVED,
            authorized_arguments=current_args,
            reason="All authority policies passed",
            policy_name="authority_layer",
        )
