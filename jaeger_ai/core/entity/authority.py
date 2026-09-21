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


class AuthorityLayer:
    """The canonical authority boundary guarding the action system.
    
    Guarantees that no proposed action reaches the environment without
    prior evaluation against registered policy rules and operator hooks.
    """

    def __init__(self, policies: list[PolicyCheckFn] | None = None) -> None:
        self._policies: list[PolicyCheckFn] = list(policies or [])

    def register_policy(self, policy: PolicyCheckFn) -> None:
        self._policies.append(policy)

    def authorize(self, proposal: ProposedAction) -> AuthorityDecision:
        """Evaluate the proposed action against all policies in order.
        
        First denial or confirmation gate immediately blocks dispatch.
        """
        current_args = proposal.arguments

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
