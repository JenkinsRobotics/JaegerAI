"""Unified Typed Effect and Verification Pipeline (Workstream 9).

Enforces the target flow:
ProposedAction
→ AuthorityDecision
→ EffectIntent
→ EffectLedger
→ Execution
→ EffectResult
→ VerificationRequest
→ VerificationResult

Connected Identifiers:
- request_id
- run_id
- proposal_id
- authority_decision_id
- effect_id
- verification_id

Invariants:
1. Tool returning ok never automatically equals objective verified.
2. Independent verification is performed wherever possible (disk probe, process probe, git probe).
3. Complete audit trail is reconstructable from identifiers.
4. Unauthorized proposals cannot create EffectIntent or execute side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
import time
from typing import Any, Callable
import uuid

from jaeger_ai.contract.schemas import (
    AuthorityDecision as ContractAuthorityDecision,
    EffectIntent,
    EffectResult,
    EffectStatus,
    ProposedAction as ContractProposedAction,
    VerificationResult,
    VerificationStatus,
)
from jaeger_ai.core.entity.verification import VerificationContract, VerificationRegistry

logger = logging.getLogger("jaeger.core.effects.pipeline")


class EffectExecutionError(RuntimeError):
    """Raised when an effect execution or authorization boundary is violated."""


@dataclass(frozen=True)
class EffectAuditRecord:
    """Consolidated record of the full effect-and-verification lifecycle."""
    request_id: str
    run_id: str
    proposal_id: str
    authority_decision_id: str
    effect_id: str
    verification_id: str
    action_type: str
    target: str
    effect_status: EffectStatus
    verification_status: VerificationStatus
    evidence: str
    timestamp: float = field(default_factory=time.time)


class EffectPipeline:
    """Coordinates side-effect declaration, ledger recording, execution, and verification."""

    def __init__(
        self,
        verification_registry: VerificationRegistry | None = None,
    ) -> None:
        self.registry = verification_registry or VerificationRegistry()

    def execute_and_verify(
        self,
        proposal: ContractProposedAction,
        authority_decision: ContractAuthorityDecision,
        executor_fn: Callable[[], Any],
        *,
        ledger: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[EffectIntent, EffectResult, VerificationResult]:
        """Execute an authorized tool action and verify its real-world outcome."""
        # 1. Authority Precondition Check
        decision_val = getattr(authority_decision, "decision", None)
        dec_str = decision_val.value if hasattr(decision_val, "value") else str(decision_val or "").lower()
        status_val = getattr(authority_decision, "status", None)
        status_str = status_val.value if hasattr(status_val, "value") else str(status_val or "").lower()

        is_auth = (
            getattr(authority_decision, "is_authorized", False)
            or dec_str in ("allow", "modify", "approved", "modified", "authoritydecisiontype.allow", "authoritydecisiontype.modify")
            or status_str in ("allow", "modify", "approved", "modified", "authorizationstatus.approved", "authorizationstatus.modified")
        )
        if not is_auth:
            raise EffectExecutionError(
                f"Cannot declare effect: Proposal {proposal.proposal_id} was not authorized "
                f"(decision={decision_val}, reason={authority_decision.reason})"
            )

        # 2. Declare EffectIntent with stable connected IDs
        effect_id = f"eff_{uuid.uuid4().hex[:12]}"
        action_target = str(
            proposal.target_path
            or proposal.arguments.get("path")
            or proposal.arguments.get("target")
            or proposal.arguments.get("CommandLine")
            or proposal.tool_name
        )
        idempotency_raw = f"{proposal.run_id}:{proposal.tool_name}:{action_target}:{sorted(proposal.arguments.items())}"
        idempotency_key = f"effkey_{hashlib.sha256(idempotency_raw.encode('utf-8')).hexdigest()[:16]}"

        intent = EffectIntent(
            effect_id=effect_id,
            request_id=proposal.request_id,
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            authority_decision_id=authority_decision.decision_id,
            idempotency_key=idempotency_key,
            action=proposal.action_type,
            target=action_target,
            payload=dict(proposal.arguments),
        )

        # 3. Ledger Registration & Execution
        raw_result: Any = None
        exec_error: str | None = None
        status = EffectStatus.APPLIED

        try:
            if ledger is not None and hasattr(ledger, "once"):
                # Use EffectLedger for strict once-only execution
                raw_result, executed = ledger.once(
                    idempotency_key,
                    proposal.action_type,
                    executor_fn,
                    run_id=proposal.run_id,
                )
                if not executed:
                    status = EffectStatus.SKIPPED_IDEMPOTENT
            else:
                raw_result = executor_fn()
        except Exception as exc:
            logger.error("Effect execution failed for %s: %s", intent.effect_id, exc)
            exec_error = str(exc)
            status = EffectStatus.FAILED

        # Check for error in return dictionary
        if isinstance(raw_result, dict) and (raw_result.get("ok") is False or raw_result.get("error")):
            status = EffectStatus.FAILED
            exec_error = str(raw_result.get("error") or "Tool reported execution failure")

        effect_result = EffectResult(
            effect_id=intent.effect_id,
            status=status,
            result=raw_result,
            error=exec_error,
        )

        # 4. Independent Verification
        verification_id = f"verif_{uuid.uuid4().hex[:12]}"

        if status == EffectStatus.FAILED:
            verification_result = VerificationResult(
                verification_id=verification_id,
                request_id=proposal.request_id,
                run_id=proposal.run_id,
                effect_id=intent.effect_id,
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=f"Execute {proposal.tool_name} on {intent.target}",
                evidence=f"Execution failed: {exec_error}",
                verifier=f"tool:{proposal.tool_name}",
                error=exec_error,
            )
        else:
            # Dispatch to independent verifiers (disk probe, process probe, etc.)
            verif_fn = self.registry._verifiers.get(proposal.action_type.lower())
            if verif_fn is not None:
                ctx = dict(context or {})
                ctx["proposal"] = proposal
                legacy_res = verif_fn(
                    f"Verify {proposal.action_type} on {intent.target}",
                    {"path": intent.target, "content": proposal.arguments.get("content")},
                    raw_result,
                    ctx,
                )
                # Map legacy result to contract VerificationResult
                v_status = VerificationStatus.OBJECTIVE_VERIFIED if legacy_res.is_verified else VerificationStatus.OBJECTIVE_FAILED
                if str(legacy_res.status).endswith("unverified"):
                    v_status = VerificationStatus.OBJECTIVE_INCONCLUSIVE

                verification_result = VerificationResult(
                    verification_id=verification_id,
                    request_id=proposal.request_id,
                    run_id=proposal.run_id,
                    effect_id=intent.effect_id,
                    status=v_status,
                    target_objective=legacy_res.target_objective,
                    evidence=legacy_res.evidence,
                    verifier=legacy_res.verifier,
                    error=legacy_res.error,
                )
            else:
                # Invariant: Tool returning ok NEVER automatically equals verified without an independent probe
                verification_result = VerificationResult(
                    verification_id=verification_id,
                    request_id=proposal.request_id,
                    run_id=proposal.run_id,
                    effect_id=intent.effect_id,
                    status=VerificationStatus.OBJECTIVE_INCONCLUSIVE,
                    target_objective=f"Verify {proposal.tool_name} outcome",
                    evidence="Tool returned success (syntactic confirmation only; no independent objective validator registered)",
                    verifier=f"tool:{proposal.tool_name}",
                )

        return intent, effect_result, verification_result
