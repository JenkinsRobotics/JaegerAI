"""
ARES SI — Response Composer.

Composes the final response that the user sees.
The worker result is NOT automatically the user response.
The SI owns the response — workers are tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import SIIdentity, WorkerResult, DataClassification


@dataclass
class SIResponse:
    """The final response presented to the user.

    This is what the user sees — not the raw worker output.
    """
    content: str                              # The composed response text
    source_worker: str | None = None          # Which worker produced the primary result
    plan_id: str | None = None                # Link to the orchestration plan
    step_id: str | None = None                # Link to the current step
    intent: str = "conversation"              # What intent was detected
    confidence: float = 1.0                   # How confident the SI is
    verification: dict[str, Any] = field(default_factory=dict)  # Verification results
    activity_summary: str | None = None       # What the SI did (for the activity timeline)
    warnings: list[str] = field(default_factory=list)  # Any warnings for the user
    needs_approval: bool = False               # Whether user approval is needed
    metadata: dict[str, Any] = field(default_factory=dict)


def compose_response(
    worker_result: str | WorkerResult,
    si_identity: SIIdentity | None = None,
    intent: str = "conversation",
    verification: dict[str, Any] | None = None,
    plan_id: str | None = None,
    step_id: str | None = None,
    activity_summary: str | None = None,
    warnings: list[str] | None = None,
    needs_approval: bool = False,
) -> SIResponse:
    """Compose the final SI response from a worker result.

    The response is presented as coming from the SI, not the worker.
    Worker identity is available in activity details but doesn't fracture
    the primary conversation.
    """
    if si_identity is None:
        si_identity = SIIdentity(name="Assistant", owner_name="User")

    # Extract content from WorkerResult or plain string
    if isinstance(worker_result, WorkerResult):
        content = worker_result.content
        source_worker = worker_result.worker_id
        confidence = worker_result.confidence or 1.0
    else:
        content = worker_result
        source_worker = None
        confidence = 1.0

    # Compose the response
    # For now, the worker content IS the response, but the SI owns it.
    # Future: add identity injection, style alignment, memory anchoring.
    composed = content

    return SIResponse(
        content=composed,
        source_worker=source_worker,
        plan_id=plan_id,
        step_id=step_id,
        intent=intent,
        confidence=confidence,
        verification=verification or {},
        activity_summary=activity_summary or f"Processed {intent} request",
        warnings=warnings or [],
        needs_approval=needs_approval,
    )


def compose_activity_entry(
    action: str,
    details: str,
    worker_id: str | None = None,
    data_shared: list[dict] | None = None,
    verification_result: str | None = None,
) -> dict[str, Any]:
    """Create an activity audit entry for the user timeline.

    Every action the SI takes should be auditable.
    """
    import time

    return {
        "timestamp": time.time(),
        "action": action,
        "details": details,
        "worker_id": worker_id,
        "data_shared": data_shared or [],
        "verification": verification_result,
    }


def compose_activity_summary(steps: list[dict]) -> str:
    """Compose a human-readable activity summary from plan steps."""
    if not steps:
        return "No actions taken"

    parts = []
    for step in steps:
        status = step.get("status", "unknown")
        objective = step.get("objective", "unknown step")
        worker = step.get("assigned_worker", "unknown")

        if status == "completed":
            parts.append(f"✓ {objective} (via {worker})")
        elif status == "failed":
            parts.append(f"✗ {objective} (failed)")
        elif status == "running":
            parts.append(f"→ {objective} (running via {worker})")
        else:
            parts.append(f"○ {objective}")

    return "\n".join(parts)