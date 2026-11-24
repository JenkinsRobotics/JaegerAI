"""Fail-closed PolicyEngine implementing PolicyPort with hook-rewrite re-evaluation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from jaeger_contracts import ActionProposal, AutonomyMode, DecisionKind, PolicyVerdict

from .canonical import is_owner_actor
from .inspectors import (
    ActorTrustInspector,
    BoundaryAndSecretsInspector,
    ControlPlaneInspector,
    DestructiveAndEvasionInspector,
    PermissionRules,
    PrecedenceAndAutonomyInspector,
    ToolInspector,
)

HookFn = Callable[[ActionProposal], Mapping[str, Any] | None]


class PolicyEngine:
    """Composable, strictly fail-closed PolicyPort engine."""

    def __init__(
        self,
        *,
        name: str = "jaeger_authority",
        rules: PermissionRules | None = None,
        global_stop_fn: Callable[[], bool] | None = None,
        extra_denied_paths: Sequence[Path] = (),
        pre_hook: HookFn | None = None,
        extra_inspectors: Sequence[ToolInspector] = (),
    ) -> None:
        self._name = name
        self._control = ControlPlaneInspector(global_stop_fn=global_stop_fn)
        self._pre_hook = pre_hook
        self._safety_inspectors: tuple[ToolInspector, ...] = (
            ActorTrustInspector(),
            BoundaryAndSecretsInspector(extra_denied_paths=extra_denied_paths),
            DestructiveAndEvasionInspector(),
            *extra_inspectors,
        )
        self._precedence = PrecedenceAndAutonomyInspector(rules)

    @property
    def name(self) -> str:
        return self._name

    def evaluate(self, proposal: ActionProposal, *, dry_run: bool = False) -> PolicyVerdict:
        trace: list[dict[str, Any]] = []
        ran: list[str] = []

        def _run_inspector(insp: ToolInspector, prop: ActionProposal) -> PolicyVerdict | None:
            ran.append(insp.name)
            verdict = insp.inspect(prop)
            trace.append({
                "check": insp.name,
                "outcome": "pass" if verdict is None else verdict.decision.value,
                "reason": "" if verdict is None else verdict.reason,
            })
            return verdict

        try:
            # 0. Control plane (GlobalStop, embodiment, structural validity) — NEVER bypassed
            if (v := _run_inspector(self._control, proposal)) is not None:
                return replace(v, inspector_chain=tuple(ran), trace=tuple(trace))

            # 1. Core non-overridable safety inspectors (run BEFORE FULL_ACCESS so
            #    destructive/evasion/secret-store invariants can NEVER be silently bypassed)
            for insp in self._safety_inspectors:
                if (v := _run_inspector(insp, proposal)) is not None:
                    return replace(v, inspector_chain=tuple(ran), trace=tuple(trace))

            # 1b. Authenticated owner FULL_ACCESS bypass (for non-destructive/non-evasion actions)
            if proposal.autonomy_mode == AutonomyMode.FULL_ACCESS and is_owner_actor(proposal.actor):
                trace.append({"check": "owner_full_access", "outcome": "allow", "reason": "Owner full access"})
                return PolicyVerdict(
                    decision=DecisionKind.ALLOW,
                    reason="Authorized by owner FULL_ACCESS mode.",
                    policy_name="owner_full_access",
                    granted_by="owner",
                    authorized_arguments=dict(proposal.arguments),
                    proposal_id=proposal.proposal_id,
                    inspector_chain=tuple(ran) + ("owner_full_access",),
                    trace=tuple(trace),
                )

            # 2. Optional pre-tool hook rewrite (skipped on dry_run; re-judged if modified!)
            current = proposal
            modified = False
            if self._pre_hook is not None and not dry_run:
                rewritten_args = self._pre_hook(current)
                if rewritten_args is not None:
                    modified = True
                    target = rewritten_args.get("path") or rewritten_args.get("TargetFile") or current.target_path
                    current = replace(
                        current,
                        arguments=dict(rewritten_args),
                        target_path=str(target) if target else None,
                    )
                    for insp in self._safety_inspectors:
                        if (v := _run_inspector(insp, current)) is not None:
                            return replace(v, inspector_chain=tuple(ran), trace=tuple(trace))

            # 3. 5-tier precedence & autonomy mode
            v = _run_inspector(self._precedence, current)
            if v is not None:
                if modified and v.decision == DecisionKind.ALLOW:
                    return replace(
                        v,
                        decision=DecisionKind.MODIFY,
                        authorized_arguments=dict(current.arguments),
                        inspector_chain=tuple(ran),
                        trace=tuple(trace),
                    )
                return replace(
                    v,
                    authorized_arguments=dict(current.arguments) if v.is_authorized else None,
                    inspector_chain=tuple(ran),
                    trace=tuple(trace),
                )

            return PolicyVerdict(
                decision=DecisionKind.MODIFY if modified else DecisionKind.ALLOW,
                reason="Authorized by PolicyEngine.",
                policy_name=self._name,
                authorized_arguments=dict(current.arguments),
                proposal_id=current.proposal_id,
                inspector_chain=tuple(ran),
                trace=tuple(trace),
            )

        except Exception as exc:
            # Strict fail-closed invariant
            trace.append({"check": "fail_closed", "outcome": "deny", "reason": str(exc)})
            return PolicyVerdict(
                decision=DecisionKind.DENY,
                reason=f"Policy evaluation error (fail-closed): {exc}",
                policy_name="fail_closed_sentinel",
                granted_by="fail_closed",
                proposal_id=proposal.proposal_id,
                inspector_chain=tuple(ran),
                trace=tuple(trace),
            )
