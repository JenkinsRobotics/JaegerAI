"""Verification Layer Contract (UPAA Principle 14 & Invariant 7).

Core Invariant:
    ATTEMPTED ACTION ≠ VERIFIED SUCCESS
    TOOL SUCCESS ≠ OBJECTIVE VERIFIED
    EFFECT RECORDED ≠ OBJECTIVE VERIFIED

Explicitly separates:
1. Execution Attempted (tool call dispatched)
2. Tool Returned Success (exit code 0 / successful tool response)
3. Effect Recorded (EffectLedger CAS / checkpoint accounting)
4. Objective Verified (ground-truth real-world state inspection confirming target goal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import time
from typing import Any, Callable

logger = logging.getLogger("jaeger.entity.verification")


class VerificationStatus(str, Enum):
    ATTEMPTED = "attempted"
    TOOL_SUCCESS = "tool_success"
    EFFECT_RECORDED = "effect_recorded"
    OBJECTIVE_VERIFIED = "objective_verified"
    OBJECTIVE_UNVERIFIED = "objective_unverified"
    OBJECTIVE_FAILED = "objective_failed"


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    target_objective: str
    evidence: str
    verifier: str
    verified_at: float = field(default_factory=time.time)
    error: str | None = None

    @property
    def is_verified(self) -> bool:
        return self.status == VerificationStatus.OBJECTIVE_VERIFIED


class VerificationContract:
    """Evaluates and records ground-truth assertions verifying real-world outcomes."""

    @staticmethod
    def verify_disk_state(
        path: Path | str,
        *,
        must_exist: bool = True,
        content_predicate: Callable[[str], bool] | None = None,
        objective: str = "Verify disk state",
    ) -> VerificationResult:
        """Inspect the real-world filesystem state independently of tool return claims."""
        target = Path(path).resolve()
        exists = target.exists()

        if must_exist and not exists:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"File {target} does not exist on disk",
                verifier="disk_probe",
                error="FileNotFound",
            )
        if not must_exist and exists:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective,
                evidence=f"File {target} unexpectedly exists on disk",
                verifier="disk_probe",
                error="FileExists",
            )

        if must_exist and content_predicate is not None:
            try:
                content = target.read_text(encoding="utf-8")
                if not content_predicate(content):
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_FAILED,
                        target_objective=objective,
                        evidence=f"Content predicate failed for {target}",
                        verifier="content_predicate",
                        error="ContentMismatch",
                    )
            except Exception as exc:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective,
                    evidence=f"Failed reading {target}: {exc}",
                    verifier="content_predicate",
                    error=str(exc),
                )

        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_VERIFIED,
            target_objective=objective,
            evidence=f"Verified real-world filesystem state at {target}",
            verifier="disk_probe",
        )

    @staticmethod
    def verify_filesystem_write(
        target_path: Path | str | None,
        expected_content: str | None = None,
        objective: str = "Verify filesystem write",
    ) -> VerificationResult:
        """Verify ground-truth outcome of a file modification or creation."""
        if not target_path:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_UNVERIFIED,
                target_objective=objective,
                evidence="No target path provided to verify",
                verifier="none",
            )
        pred = (lambda c: expected_content in c) if expected_content is not None else None
        return VerificationContract.verify_disk_state(
            target_path,
            must_exist=True,
            content_predicate=pred,
            objective=objective,
        )

    @staticmethod
    def evaluate_tool_consequence(
        tool_name: str,
        tool_return: Any,
        *,
        objective: str = "",
        external_verifier: Callable[[Any], bool] | None = None,
    ) -> VerificationResult:
        """Distinguish raw tool success from independent objective verification."""
        is_tool_ok = False
        if isinstance(tool_return, dict):
            is_tool_ok = bool(tool_return.get("ok", True)) and not tool_return.get("error")
        elif tool_return is not None:
            is_tool_ok = True

        if not is_tool_ok:
            return VerificationResult(
                status=VerificationStatus.OBJECTIVE_FAILED,
                target_objective=objective or f"Execute tool {tool_name}",
                evidence=f"Tool {tool_name} reported execution error",
                verifier=f"tool:{tool_name}",
                error=str(tool_return.get("error") if isinstance(tool_return, dict) else "Tool error"),
            )

        # Tool returned success; check if an independent verifier validates the objective
        if external_verifier is not None:
            try:
                verified = external_verifier(tool_return)
                if verified:
                    return VerificationResult(
                        status=VerificationStatus.OBJECTIVE_VERIFIED,
                        target_objective=objective or f"Verified outcome of {tool_name}",
                        evidence="Independent verifier confirmed objective state",
                        verifier="external_verifier",
                    )
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective or f"Outcome of {tool_name}",
                    evidence="Tool reported success, but external verifier found target objective unfulfilled",
                    verifier="external_verifier",
                    error="ObjectiveVerificationFailed",
                )
            except Exception as exc:
                return VerificationResult(
                    status=VerificationStatus.OBJECTIVE_FAILED,
                    target_objective=objective or f"Outcome of {tool_name}",
                    evidence=f"External verifier threw an exception: {exc}",
                    verifier="external_verifier",
                    error=str(exc),
                )

        # Without an independent validator, success is only tool-syntactic, not objective-verified
        return VerificationResult(
            status=VerificationStatus.OBJECTIVE_UNVERIFIED,
            target_objective=objective or f"Execute tool {tool_name}",
            evidence=f"Tool {tool_name} returned success (syntactic confirmation only; no independent objective validator)",
            verifier=f"tool:{tool_name}",
        )
