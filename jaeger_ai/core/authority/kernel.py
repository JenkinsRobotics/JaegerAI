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
#: Tools that change who Jaeger is (name, soul, character). Only an owner-class actor
#: (an authenticated ``owner:<client>`` turn) may run them: not an outside caller, and
#: not a background turn the entity started for itself (``agent:jaeger``).
IDENTITY_TOOL_IDS = frozenset({"set_name", "update_soul", "adjust_trait"})
#: Tools that write durable memory. The resident Entity is the one memory writer; an
#: outside caller's turn (mcp, a2a, helper) may read memory but not write it.
MEMORY_WRITE_TOOL_IDS = frozenset({"remember", "forget", "memory", "remember_person"})
OWNER_ACTOR_PREFIXES = ("owner", "human")
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


def is_owner_actor(actor: str) -> bool:
    a = (actor or "").strip().lower()
    return any(a == p or a.startswith(p + ":") for p in OWNER_ACTOR_PREFIXES)


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


def _resolve_instance_root(
    proposal: ProposedAction,
    *,
    instance_root: Path | str | None = None,
    allow_runtime: bool = True,
) -> Path | None:
    """The bound instance directory. ``allow_runtime=False`` (dry runs) never
    touches ``EntityRuntime.get_singleton()``, which can start a resident."""
    if instance_root:
        return Path(instance_root)
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
    if not allow_runtime:
        return None
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

    def evaluate(
        self,
        proposal: ProposedAction,
        *,
        dry_run: bool = False,
        instance_root: Path | str | None = None,
        extra_rules: Sequence["ReviewRule"] = (),
        trace: list[dict[str, Any]] | None = None,
    ) -> AuthorityDecision:
        """Evaluate a ProposedAction against the unified policy hierarchy.

        Evaluates:
        0. Control plane (Global Stop, lifecycle owner) and structure
        1. Security Policy & Safety Mode (PAUSED, READ_ONLY)
        2. Identity & Trust Scope
        2b. Destructive / irreversible actions -> fresh owner approval
            (non-overridable; see authority/destructive.py)
        2c. Review rules (team over local; rules only restrict, never grant)
        3. Capability Allowlist & Current Grants
        4. Protected System Targets
        5. Operator Shell Hooks (pre_tool_call)
        6. Commissioning & Operator Policy Grants
        7. Tier-based Human Approval

        ``dry_run=True`` is the side-effect-free preview (GB-031): the same
        checks in the same order, except operator hooks are NOT run (they are
        arbitrary operator code), nothing is written, no event or audit record
        is produced, no runtime is initialized (the instance root comes only
        from ``instance_root``/the proposal context, never ``get_singleton``)
        and state paths are resolved without ``mkdir`` or migration.
        ``extra_rules`` previews unsaved rule edits; they are never stored.
        ``trace`` (a list) receives one ``{"check", "outcome", ...}`` row per step.
        """
        current_args = dict(proposal.arguments)
        modified_args: dict[str, Any] | None = None
        steps = trace if trace is not None else []

        def step(name: str, decision: AuthorityDecision | None, **extra: Any) -> AuthorityDecision | None:
            row: dict[str, Any] = {"check": name, "outcome": "pass" if decision is None else decision.decision.value}
            if decision is not None:
                row["reason"] = decision.reason
                row["policy_name"] = decision.policy_name
            row.update(extra)
            steps.append(row)
            return decision

        try:
            # ── 0. Control plane: Stop, lifecycle owner, embodiment ──────────
            if (d := step("control_plane", self._check_control_plane(proposal, dry_run=dry_run))) is not None:
                return d
            # ── 0. Structural validity: unknown tool/action/tier → DENY ─────
            if (d := step("structure", self._check_structure(proposal))) is not None:
                return d
            # ── 1. Security Policy & Safety Mode ─────────────────────────────
            if (d := step("security_mode", self._check_security_mode(proposal))) is not None:
                return d
            # ── 2. Identity & Trust Restrictions ─────────────────────────────
            if (d := step("identity_trust", self._check_identity_trust(proposal))) is not None:
                return d
            # ── 2a. Other agent frameworks: the owner's per-framework grant ──
            if (d := step("framework_grant", self._check_framework_grant(proposal))) is not None:
                return d
            # ── 2b. Destructive / irreversible actions (non-overridable) ─────
            # Needs a fresh owner approval for this call. Evaluated before
            # grants, operator hooks and commissioning so none can waive it.
            if (d := step("destructive", self._check_destructive(proposal, proposal.arguments))) is not None:
                return d
            # ── 2c. Review rules: team policy over local rules ───────────────
            rule_decision, rule_info = self._check_review_rules(
                proposal, instance_root=instance_root, dry_run=dry_run, extra_rules=extra_rules)
            if (d := step("review_rules", rule_decision, **rule_info)) is not None:
                return d
            # ── 3. Capability Allowlist & Current Grants ──────────────────────
            if (d := step("capability_grants", self._check_capability_grants(proposal))) is not None:
                return d
            # ── 4. Protected Targets ─────────────────────────────────────────
            if (d := step("protected_targets", self._check_protected_targets(proposal))) is not None:
                return d
            # ── 5. Operator Shell Hooks (pre_tool_call) ──────────────────────
            if dry_run:
                steps.append({"check": "shell_hooks", "outcome": "not_evaluated",
                              "reason": "Operator hooks are not run in a dry run; a real call still runs them."})
            else:
                hook_decision, modified_args = self._check_shell_hooks(proposal, current_args)
                if (d := step("shell_hooks", hook_decision)) is not None:
                    return d
                if modified_args is not None:
                    current_args = modified_args
                    # A hook rewrite is judged again: it cannot turn a call into
                    # a destructive one without the fresh-approval gate.
                    destructive = self._check_destructive(proposal, current_args)
                    if (d := step("destructive_after_hook", destructive)) is not None:
                        return d
            # ── 6. Commissioning & Operator Policy Grants ────────────────────
            comm = self._check_commissioning_policy(
                proposal, current_args, instance_root=instance_root, dry_run=dry_run)
            if (d := step("commissioning_policy", comm)) is not None:
                return d
            # ── 7. Tier-based Approval Gate ──────────────────────────────────
            if (d := step("tier_approval", self._check_tier_approval(proposal))) is not None:
                return d

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
            steps.append({"check": "fail_closed", "outcome": "deny", "reason": str(exc)})
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason=f"Policy evaluation failure: {exc} (fail-closed)",
                policy_name="fail_closed_sentinel",
                granted_by="fail_closed",
                proposal_id=proposal.proposal_id,
            )

    def preview(
        self,
        proposal: ProposedAction,
        *,
        instance_root: Path | str | None = None,
        extra_rules: Sequence["ReviewRule"] = (),
    ) -> dict[str, Any]:
        """Effective-decision preview: a dry run, returned as plain JSON data.

        Never authorizes anything (``action_authorized`` is always False): a
        real call is evaluated again, with hooks, when it is proposed.
        """
        trace: list[dict[str, Any]] = []
        decision = self.evaluate(proposal, dry_run=True, instance_root=instance_root,
                                 extra_rules=extra_rules, trace=trace)
        rules_row = next((row for row in trace if row.get("check") == "review_rules"), {})
        return {
            "dry_run": True,
            "action_authorized": False,
            "hooks_evaluated": False,
            "decision": decision.decision.value,
            "reason": decision.reason,
            "policy_name": decision.policy_name,
            "tool_id": canonical_tool_id(proposal.tool_name),
            "steps": trace,
            "winning_rule": rules_row.get("winning_rule"),
            "overridden_rules": rules_row.get("overridden_rules", []),
            "rule_revisions": rules_row.get("revisions"),
            "pending_rules_previewed": len(extra_rules),
        }

    # ── Check Implementations ────────────────────────────────────────────────
    #
    # Every sub-check fails CLOSED: an exception inside a check is a DENY, never
    # "no objection" (Constitution invariant 11). Phase 0 found four sub-checks
    # that logged at debug level and returned None on error.

    def _check_control_plane(self, proposal: ProposedAction, *, dry_run: bool = False) -> AuthorityDecision | None:
        """Stop and a missing owner fail closed. Embodiment stays off.

        A dry run resolves the latch/lease paths purely (no ``mkdir`` or
        legacy migration); the files are only read either way."""
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
                stopped = (_pure_global_stop() if dry_run else GlobalStop.load()).engaged()
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
            decision = (_pure_lifecycle_lease() if dry_run else LifecycleLease.load()).decide()
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
        if canonical_tool_id(proposal.tool_name) in IDENTITY_TOOL_IDS and not is_owner_actor(actor):
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason=f"Actor {actor!r} may not change Jaeger's identity ({proposal.tool_name!r} is owner-only)",
                policy_name="identity_authority",
                granted_by="policy_kernel",
                proposal_id=proposal.proposal_id,
            )
        if is_untrusted_actor(actor) and canonical_tool_id(proposal.tool_name) in MEMORY_WRITE_TOOL_IDS:
            return AuthorityDecision(
                decision=AuthorityDecisionType.DENY,
                reason=f"Actor {actor!r} is an outside caller and may not write durable memory ({proposal.tool_name!r})",
                policy_name="memory_authority",
                granted_by="policy_kernel",
                proposal_id=proposal.proposal_id,
            )
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

    def _check_framework_grant(self, proposal: ProposedAction) -> AuthorityDecision | None:
        """framework_read / framework_delegate need the owner's grant for that
        framework and capability (set only from the owner's own surfaces)."""
        name = str(proposal.tool_name or "").strip().lower()
        if name not in {"framework_read", "framework_delegate"}:
            return None
        try:
            from jaeger_ai.core.frameworks.grants import FrameworkGrants

            fid = str(proposal.arguments.get("framework") or "")
            if name == "framework_delegate":
                cap = "delegate"
            else:
                cap = "read_memory" if str(proposal.arguments.get("kind") or "sessions") == "memory" else "read_sessions"
            if not FrameworkGrants().is_granted(fid, cap):
                return _deny(proposal, f"The owner has not granted {cap} for framework {fid!r}", "framework_grant")
        except Exception as exc:  # noqa: BLE001
            return _deny(proposal, f"Framework grant check failed: {exc} (fail-closed)", "framework_grant")
        return None

    def _check_review_rules(
        self,
        proposal: ProposedAction,
        *,
        instance_root: Path | str | None = None,
        dry_run: bool = False,
        extra_rules: Sequence["ReviewRule"] = (),
    ) -> tuple[AuthorityDecision | None, dict[str, Any]]:
        """Owner review rules (GB-031) and app grants (GB-027): team over local.

        Rules only restrict: a matching ``deny`` denies and a matching
        ``require_approval`` asks, team before local; an ``allow`` rule never
        grants anything and never skips a later gate. Unreadable rules deny.
        """
        try:
            root = _resolve_instance_root(proposal, instance_root=instance_root, allow_runtime=not dry_run)
            store = ReviewRuleStore.for_instance(root) if root is not None else None
            stored = store.active_rules() if store is not None else []
            revisions = store.revisions() if store is not None else None
            pending = list(extra_rules) if dry_run else []
            return effective_rule_decision(proposal, stored, pending, revisions)
        except Exception as exc:  # noqa: BLE001
            logger.error("Review-rule check failed for %r: %s (fail-closed)", proposal.tool_name, exc)
            return _deny(proposal, f"Review rules unreadable or invalid: {exc} (fail-closed)", "review_rules"), {}

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

    def _check_destructive(
        self, proposal: ProposedAction, arguments: Mapping[str, Any],
    ) -> AuthorityDecision | None:
        """Destructive or irreversible -> REQUIRE_APPROVAL (fresh, per call).

        Not overridable: standing "always" grants, autonomy "auto",
        commissioning policy and hooks never reach this decision, and the
        executor answers it only through a provider that asks a human for
        this call (``fresh_approval``). Detection failure fails closed.
        """
        try:
            from jaeger_ai.core.authority.destructive import destructive_reason
            reason = destructive_reason(proposal.tool_name, arguments)
        except Exception as exc:  # noqa: BLE001
            logger.error("Destructive-action check failed for %r: %s (fail-closed)", proposal.tool_name, exc)
            return _deny(proposal, f"Destructive-action check failed: {exc} (fail-closed)", "destructive_action")
        if not reason:
            return None
        return AuthorityDecision(
            decision=AuthorityDecisionType.REQUIRE_APPROVAL,
            reason=f"Destructive or irreversible action needs a fresh owner approval: {reason}",
            policy_name="destructive_action",
            granted_by="policy_kernel",
            proposal_id=proposal.proposal_id,
        )

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
        *,
        instance_root: Path | str | None = None,
        dry_run: bool = False,
    ) -> AuthorityDecision | None:
        try:
            from jaeger_ai.core.instance.commissioning import load_authority_policy_checked

            root = _resolve_instance_root(proposal, instance_root=instance_root, allow_runtime=not dry_run)
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


# ── Dry-run state paths (no mkdir, no migration) ─────────────────────────────
def _pure_state_root() -> Path:
    from jaeger_ai.core.instance.instance import StatePaths
    return StatePaths.resolve().state_root


def _pure_global_stop():
    import os
    from jaeger_ai.core.gateway.global_stop import GlobalStop, _ENV
    raw = os.environ.get(_ENV, "").strip()
    return GlobalStop(Path(raw).expanduser() if raw else _pure_state_root() / "control" / "global-stop.json")


def _pure_lifecycle_lease():
    import os
    from jaeger_ai.core.runtime import lifecycle_lease as ll
    raw = os.environ.get(ll._ENV, "").strip()
    path = Path(raw).expanduser() if raw else _pure_state_root() / "control" / "lifecycle-lease.json"
    return ll.LifecycleLease(path, grace_seconds=ll.SHUTDOWN_GRACE_S, suspend_after=ll.SUSPEND_AFTER_S)


# ── Review rules: versioned storage (GB-031 team/local rules, GB-027 app grants) ──
REVIEW_RULES_FILENAME = "authority_review_rules.json"
RULE_SCOPES = ("team", "local")
RULE_EFFECTS = ("deny", "require_approval", "allow")
#: Lower ranks win. ``allow`` never decides: rules only restrict.
_RULE_RANK = {("team", "deny"): 0, ("local", "deny"): 1,
              ("team", "require_approval"): 2, ("local", "require_approval"): 3}


class ReviewRuleError(ValueError):
    """Rules file is unreadable, malformed, or a rule is invalid."""


class StaleRuleRevision(ReviewRuleError):
    """The editor's base revision is behind the stored revision for that scope."""

    def __init__(self, scope: str, expected: int, current: int) -> None:
        super().__init__(f"{scope} rules are at revision {current}, not {expected}; reload and re-apply")
        self.scope, self.expected, self.current = scope, expected, current


@dataclass(frozen=True)
class ReviewRule:
    """One owner review rule. ``subject`` is a canonical tool id, ``*``, or
    ``app:<bundle id>`` (with ``capability`` e.g. ``screen_view``/``input``)."""
    scope: str
    subject: str
    effect: str
    principal: str = "*"
    capability: str = ""
    note: str = ""
    revision: int = 0
    provenance: str = ""
    created_at: float = 0.0

    @property
    def key(self) -> str:
        return "|".join((self.scope, self.subject, self.principal, self.capability))

    @property
    def rule_id(self) -> str:
        import hashlib
        return "rule_" + hashlib.sha256(self.key.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def build(cls, raw: Mapping[str, Any], **overrides: Any) -> "ReviewRule":
        data = {**dict(raw or {}), **overrides}
        scope = str(data.get("scope") or "").strip().lower()
        effect = str(data.get("effect") or "").strip().lower()
        subject_raw = str(data.get("subject") or "").strip()
        if scope not in RULE_SCOPES:
            raise ReviewRuleError(f"scope must be one of {RULE_SCOPES}")
        if effect not in RULE_EFFECTS:
            raise ReviewRuleError(f"effect must be one of {RULE_EFFECTS}")
        if not subject_raw:
            raise ReviewRuleError("subject is required")
        if subject_raw == "*" or subject_raw.lower().startswith("app:"):
            subject = subject_raw if subject_raw == "*" else "app:" + subject_raw[4:].strip()
        else:
            subject = canonical_tool_id(subject_raw)
        if subject == "app:":
            raise ReviewRuleError("app subject needs an app id")
        capability = str(data.get("capability") or "").strip().lower()
        if capability and not subject.startswith("app:"):
            raise ReviewRuleError("capability applies to app subjects only")
        return cls(scope=scope, subject=subject, effect=effect,
                   principal=str(data.get("principal") or "*").strip() or "*",
                   capability=capability, note=str(data.get("note") or "")[:500],
                   revision=int(data.get("revision") or 0), provenance=str(data.get("provenance") or ""),
                   created_at=float(data.get("created_at") or 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {"rule_id": self.rule_id, "scope": self.scope, "subject": self.subject,
                "effect": self.effect, "principal": self.principal, "capability": self.capability,
                "note": self.note, "revision": self.revision, "provenance": self.provenance,
                "created_at": self.created_at}

    def matches(self, proposal: ProposedAction) -> bool:
        actor = (proposal.actor or "").strip()
        if self.principal != "*" and actor != self.principal and not actor.startswith(self.principal + ":"):
            return False
        if self.subject.startswith("app:"):
            ctx = proposal.context or {}
            app = str(ctx.get("app_id") or proposal.arguments.get("app_id") or "")
            if app != self.subject[4:]:
                return False
            wanted = str(ctx.get("capability") or proposal.arguments.get("capability") or "").lower()
            return not self.capability or self.capability == wanted
        return self.subject == "*" or self.subject == canonical_tool_id(proposal.tool_name)


class ReviewRuleStore:
    """Append-only revision history in ``<instance>/authority_review_rules.json``.

    Each scope (team, local) has its own monotonically increasing revision.
    Saving a rule identical to the current one for its key, or replaying an
    ``idempotency_key``, returns the existing revision; an editor whose
    ``expected_revision`` is stale is refused (``StaleRuleRevision``).
    Reading never creates the file.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @classmethod
    def for_instance(cls, instance_root: Path | str) -> "ReviewRuleStore":
        from jaeger_ai.core.instance.first_boot import instance_dir
        return cls(instance_dir(instance_root) / REVIEW_RULES_FILENAME)

    def _read(self) -> dict[str, Any]:
        import json
        if not self.path.exists():
            return {"version": 1, "revisions": {"team": 0, "local": 0}, "history": [], "idempotency": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ReviewRuleError(f"{REVIEW_RULES_FILENAME} unreadable: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("history"), list) \
                or not isinstance(data.get("revisions"), dict):
            raise ReviewRuleError(f"{REVIEW_RULES_FILENAME} is malformed")
        data.setdefault("idempotency", {})
        return data

    def revisions(self) -> dict[str, int]:
        revs = self._read()["revisions"]
        return {scope: int(revs.get(scope) or 0) for scope in RULE_SCOPES}

    def history(self) -> list[ReviewRule]:
        return [ReviewRule.build(row) for row in self._read()["history"]]

    def active_rules(self) -> list[ReviewRule]:
        current: dict[str, ReviewRule] = {}
        for rule in self.history():
            current[rule.key] = rule        # later revisions supersede earlier ones
        return list(current.values())

    def save(
        self,
        raw: Mapping[str, Any],
        *,
        expected_revision: int | None = None,
        idempotency_key: str = "",
        provenance: str = "",
    ) -> tuple[ReviewRule, bool]:
        """Store one rule revision. Returns ``(rule, created)``."""
        import fcntl
        import json
        import os

        rule = ReviewRule.build(raw, revision=0, provenance=provenance, created_at=0.0)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        with open(lock_path, "a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            data = self._read()
            if idempotency_key and idempotency_key in data["idempotency"]:
                ref = data["idempotency"][idempotency_key]
                for row in data["history"]:
                    stored = ReviewRule.build(row)
                    if stored.key == ref.get("key") and stored.revision == ref.get("revision"):
                        return stored, False
            current = {r.key: r for r in (ReviewRule.build(row) for row in data["history"])}.get(rule.key)
            if current is not None and (current.effect, current.note) == (rule.effect, rule.note):
                if idempotency_key:
                    data["idempotency"][idempotency_key] = {"key": current.key, "revision": current.revision}
                    self._write(data)
                return current, False
            have = int(data["revisions"].get(rule.scope) or 0)
            if expected_revision is not None and int(expected_revision) != have:
                raise StaleRuleRevision(rule.scope, int(expected_revision), have)
            stored = ReviewRule.build(rule.to_dict(), revision=have + 1, provenance=provenance,
                                      created_at=time.time())
            data["revisions"][rule.scope] = have + 1
            data["history"].append(stored.to_dict())
            if idempotency_key:
                data["idempotency"][idempotency_key] = {"key": stored.key, "revision": stored.revision}
            self._write(data)
            return stored, True

    def _write(self, data: dict[str, Any]) -> None:
        import json
        import os
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)


def effective_rule_decision(
    proposal: ProposedAction,
    stored: Sequence[ReviewRule],
    pending: Sequence[ReviewRule] = (),
    revisions: Mapping[str, int] | None = None,
) -> tuple[AuthorityDecision | None, dict[str, Any]]:
    """The winning rule for ``proposal`` and why. Pending (unsaved) rules
    replace stored rules with the same key, for preview only."""
    by_key = {rule.key: rule for rule in stored}
    for rule in pending:
        by_key[rule.key] = rule
    pending_keys = {rule.key for rule in pending}
    matching = [rule for rule in by_key.values() if rule.matches(proposal)]

    def view(rule: ReviewRule) -> dict[str, Any]:
        return {**rule.to_dict(), "pending": rule.key in pending_keys}

    ranked = sorted((r for r in matching if (r.scope, r.effect) in _RULE_RANK),
                    key=lambda r: (_RULE_RANK[(r.scope, r.effect)], r.subject == "*"))
    info: dict[str, Any] = {"revisions": dict(revisions) if revisions is not None else None,
                            "matched": len(matching)}
    if not ranked:
        info["winning_rule"] = None
        info["overridden_rules"] = []
        if matching:
            info["note"] = "Matching allow rules grant nothing; later gates still decide."
            info["considered_allow_rules"] = [view(r) for r in matching]
        return None, info
    winner = ranked[0]
    info["winning_rule"] = view(winner)
    info["overridden_rules"] = [
        {**view(r), "overridden_by": winner.rule_id,
         "why": "team rule wins" if winner.scope == "team" and r.scope == "local" else "a stricter rule wins"}
        for r in matching if r is not winner
    ]
    decision = AuthorityDecisionType.DENY if winner.effect == "deny" else AuthorityDecisionType.REQUIRE_APPROVAL
    what = f"{winner.subject}" + (f" ({winner.capability})" if winner.capability else "")
    return AuthorityDecision(
        decision=decision,
        reason=f"{winner.scope.capitalize()} review rule {winner.rule_id} rev {winner.revision}: "
               f"{winner.effect.replace('_', ' ')} {what}",
        policy_name=f"review_rules:{winner.scope}",
        granted_by="review_rules",
        proposal_id=proposal.proposal_id,
    ), info
