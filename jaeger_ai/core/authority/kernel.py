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
import re
import time
from typing import Any, Callable, Mapping, Sequence
import uuid

logger = logging.getLogger("jaeger.core.authority.kernel")


# ── Canonical tool identity ──────────────────────────────────────────────────
#: Policy rules are written against canonical ids so an aliased or renamed tool
#: cannot slip past a rule written for another name. Phase 0 found the live
#: shell tool is ``terminal`` while every shell rule matched only
#: run_shell/exec/bash/run_command, so no shell rule ever fired.
TOOL_ALIASES: Mapping[str, str] = {
    # local shell
    "shell": "shell", "terminal": "shell", "run_shell": "shell", "exec": "shell",
    "bash": "shell", "sh": "shell", "zsh": "shell", "run_command": "shell",
    "shell_exec": "shell", "execute_command": "shell", "run_terminal_command": "shell",
    # remote shell
    "remote_terminal": "remote_shell", "remote_shell": "remote_shell", "ssh": "remote_shell",
    # arbitrary code execution
    "execute_code": "code_exec", "run_python": "code_exec", "run_in_venv": "code_exec",
    # git / files
    "git_push": "git_push", "push": "git_push",
    "write_file": "write_file", "edit_file": "write_file", "append_file": "write_file",
    "patch": "write_file", "delete_file": "delete_file",
}
SHELL_TOOL_IDS = frozenset({"shell", "remote_shell"})
#: Canonical tools an untrusted/external caller may never run.
PRIVILEGED_TOOL_IDS = frozenset({"shell", "remote_shell", "code_exec", "deploy", "git_push"})
#: Actors (exact, or ``<prefix>:<name>``) that are outside callers, not the owner.
UNTRUSTED_ACTOR_PREFIXES = ("guest", "untrusted", "external_agent", "helper", "mcp", "a2a")
KNOWN_TIERS = frozenset({"read_only", "write_local", "external_effect", "hardware", "privileged"})
KNOWN_ACTION_TYPES = frozenset({"tool_call"})


def canonical_tool_id(name: Any) -> str:
    """Normalize a tool name to its canonical policy id ("" if unusable).

    Case, surrounding whitespace and ``-``/``_`` differences are ignored, and a
    namespaced name (``mcp__jaeger__terminal``, ``functions.bash``,
    ``code:run_shell``) resolves through its last segment when that segment is
    a known alias.
    """
    raw = str(name or "").strip().lower().replace("-", "_")
    if not raw:
        return ""
    if raw in TOOL_ALIASES:
        return TOOL_ALIASES[raw]
    for sep in ("__", ".", ":", "/"):
        if sep in raw:
            tail = raw.rsplit(sep, 1)[-1]
            if tail in TOOL_ALIASES:
                return TOOL_ALIASES[tail]
    return raw


def is_untrusted_actor(actor: str) -> bool:
    a = (actor or "").strip().lower()
    return any(a == p or a.startswith(p + ":") for p in UNTRUSTED_ACTOR_PREFIXES)


def _deny(proposal: "ProposedAction", reason: str, policy_name: str) -> "AuthorityDecision":
    return AuthorityDecision(
        decision=AuthorityDecisionType.DENY,
        reason=reason,
        policy_name=policy_name,
        granted_by="fail_closed",
        proposal_id=proposal.proposal_id,
    )


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
            # ── 0. Control plane: Stop, lifecycle owner, embodiment ──────────
            control = self._check_control_plane(proposal)
            if control is not None:
                return control

            # ── 0. Structural validity: unknown tool/action/tier → DENY ─────
            structural = self._check_structure(proposal)
            if structural is not None:
                return structural

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
    #
    # Every sub-check fails CLOSED: an exception inside a check is a DENY, never
    # "no objection" (Constitution invariant 11). Phase 0 found four sub-checks
    # that logged at debug level and returned None on error.

    def _check_control_plane(self, proposal: ProposedAction) -> AuthorityDecision | None:
        """Stop and a missing owner fail closed. Embodiment stays off."""
        name = str(proposal.tool_name or "").strip().lower()
        if name.startswith("mc_") or "minecraft" in name:
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason="Embodiment is disabled until the control-plane release gate passes.",
                policy_name="embodiment_gate",
                proposal_id=proposal.proposal_id,
            )
        try:
            from jaeger_ai.core.gateway.global_stop import GlobalStop, GlobalStopError
            try:
                stopped = GlobalStop.load().engaged()
            except GlobalStopError:
                stopped = True
            if stopped:
                return AuthorityDecision(
                    decision=AuthorityDecisionType.DENY,
                    reason="global stop",
                    policy_name="global_stop",
                    proposal_id=proposal.proposal_id,
                )
        except Exception:
            logger.exception(
                "Global stop check failed for %r (fail-closed)",
                proposal.tool_name,
            )
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason="global stop unavailable",
                policy_name="global_stop",
                proposal_id=proposal.proposal_id,
            )
        try:
            from jaeger_ai.core.runtime.lifecycle_lease import LifecycleLease
            decision = LifecycleLease.load().decide()
        except Exception:
            logger.exception(
                "Lifecycle lease check failed for %r (fail-closed)",
                proposal.tool_name,
            )
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason="lifecycle lease unavailable",
                policy_name="lifecycle_lease",
                proposal_id=proposal.proposal_id,
            )
        if not decision.privileged_work_allowed:
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason=decision.reason,
                policy_name="lifecycle_lease",
                proposal_id=proposal.proposal_id,
            )
        return None

    def _check_structure(self, proposal: ProposedAction) -> AuthorityDecision | None:
        if not canonical_tool_id(proposal.tool_name):
            return _deny(proposal, "Unknown tool: empty or unusable tool name", "unknown_tool")
        if str(proposal.action_type or "") not in KNOWN_ACTION_TYPES:
            return _deny(proposal, f"Unknown action type {proposal.action_type!r}", "unknown_action")
        if str(proposal.tier or "") not in KNOWN_TIERS:
            return _deny(proposal, f"Unknown or non-grantable tier {proposal.tier!r}", "unknown_tier")
        if not isinstance(proposal.arguments, Mapping):
            return _deny(proposal, "Tool arguments must be a mapping", "malformed_arguments")
        return None

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
            logger.error("Safety policy mode check failed for %r: %s (fail-closed)", proposal.tool_name, exc)
            return _deny(proposal, f"Safety mode check failed: {exc} (fail-closed)", "safety_mode")
        return None

    def _check_identity_trust(self, proposal: ProposedAction) -> AuthorityDecision | None:
        actor = (proposal.actor or "").strip()
        if not actor:
            return _deny(proposal, "Missing caller identity (actor) on proposed action", "identity_required")
        if is_untrusted_actor(actor):
            if canonical_tool_id(proposal.tool_name) in PRIVILEGED_TOOL_IDS:
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
            logger.error("Allowlist grant check failed for %r: %s (fail-closed)", proposal.tool_name, exc)
            return _deny(proposal, f"Capability grant check failed: {exc} (fail-closed)", "tool_allowlist")
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
        # Check git branch push protection (canonical: git_push tool, or a
        # shell-family tool whose command line runs ``git push``)
        cid = canonical_tool_id(proposal.tool_name)
        command_line = str(proposal.arguments.get("CommandLine") or proposal.arguments.get("command") or "")
        shell_push = cid in SHELL_TOOL_IDS and re.search(r"\bgit\b[^;&|]*\bpush\b", command_line)
        if cid == "git_push" or shell_push or "push" in str(proposal.arguments.get("CommandLine", "")):
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
            logger.error("Shell hooks check failed for %r: %s (fail-closed)", proposal.tool_name, exc)
            return _deny(proposal, f"Operator hook check failed: {exc} (fail-closed)", "shell_hooks"), None
        return None, None

    def _check_commissioning_policy(
        self,
        proposal: ProposedAction,
        args: dict[str, Any],
    ) -> AuthorityDecision | None:
        try:
            from jaeger_ai.core.instance.commissioning import load_authority_policy_checked

            root = _resolve_instance_root(proposal)
            if root is None:
                # No instance bound (embedders, unit tests). Not an error; the
                # tool body's tier gate still applies.
                return None
            # A missing file is "never commissioned" (established instances keep
            # the tier-gate posture); an unreadable or malformed file RAISES and
            # is denied below. It used to read as {} = no objection.
            policy = load_authority_policy_checked(root)
            if not policy:
                return None

            tool = canonical_tool_id(proposal.tool_name)
            shell_cfg = policy.get("shell") or {}
            shell_mode = str(shell_cfg.get("risk_mode") or "confirm")
            if tool in SHELL_TOOL_IDS:
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
            if tool in {"write_file", "delete_file"}:
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
            logger.error("Commissioning policy check failed for %r: %s (fail-closed)", proposal.tool_name, exc)
            return _deny(proposal, f"Commissioning policy unreadable or invalid: {exc} (fail-closed)",
                         "commissioning_authority")
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
