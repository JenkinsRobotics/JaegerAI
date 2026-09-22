"""
ARES SI — Planner.

Breaks a goal into steps, assigns workers, and creates a Plan
that can be persisted and resumed across app restarts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .types import Plan, Step, PlanStatus, StepStatus, WorkerCapability
from .worker_registry import get_registry


# ── Step templates for common patterns ─────────────────────────────────

_TASK_PATTERNS: dict[str, list[dict]] = {
    "code_generation": [
        {"objective": "Understand the code request and retrieve relevant context", "required_capabilities": ["conversation"]},
        {"objective": "Generate or modify code", "required_capabilities": ["code_generation"]},
        {"objective": "Verify the code (lint, type check, test)", "required_capabilities": ["code_generation"]},
    ],
    "research": [
        {"objective": "Search for relevant information", "required_capabilities": ["research"]},
        {"objective": "Synthesize findings", "required_capabilities": ["conversation"]},
    ],
    "action": [
        {"objective": "Validate the action is safe and approved", "required_capabilities": ["conversation"]},
        {"objective": "Execute the action", "required_capabilities": ["terminal"]},
        {"objective": "Verify the action succeeded", "required_capabilities": ["conversation"]},
    ],
    "memory": [
        {"objective": "Retrieve relevant memories from Journal", "required_capabilities": ["conversation"]},
        {"objective": "Present findings to the user", "required_capabilities": ["conversation"]},
    ],
}


def create_plan(
    goal: str,
    intent: str | None = None,
    conversation_id: str | None = None,
    simple: bool = False,
) -> Plan:
    """Create a plan for a goal.

    For simple tasks (intent=conversation), creates a single-step plan.
    For complex tasks, breaks the goal into steps using task patterns.
    """
    plan_id = str(uuid.uuid4())
    now = time.time()

    # Simple tasks get a single step
    if simple or intent == "conversation":
        return Plan(
            plan_id=plan_id,
            goal=goal,
            status=PlanStatus.PENDING,
            steps=[
                Step(
                    step_id=f"{plan_id}_s1",
                    objective=goal,
                    required_capabilities=["conversation"],
                    status=StepStatus.PENDING,
                )
            ],
            created_at=now,
            updated_at=now,
            conversation_id=conversation_id,
        )

    # Complex tasks get multi-step plans
    pattern = _TASK_PATTERNS.get(intent or "research", _TASK_PATTERNS["research"])

    steps = []
    for i, template in enumerate(pattern):
        steps.append(Step(
            step_id=f"{plan_id}_s{i+1}",
            objective=template["objective"],
            required_capabilities=template.get("required_capabilities", ["conversation"]),
            dependencies=[f"{plan_id}_s{j+1}" for j in range(i)] if i > 0 else [],
            status=StepStatus.PENDING,
        ))

    return Plan(
        plan_id=plan_id,
        goal=goal,
        status=PlanStatus.PENDING,
        steps=steps,
        created_at=now,
        updated_at=now,
        conversation_id=conversation_id,
    )


def assign_workers(plan: Plan) -> Plan:
    """Assign the best available worker to each step.

    Uses the worker registry to find eligible workers based on:
    1. Required capabilities
    2. Privacy eligibility (uses personal data sensitivity by default)
    3. Availability
    """
    registry = get_registry()

    for step in plan.steps:
        if step.assigned_worker:
            continue  # Already assigned

        if not step.required_capabilities:
            step.assigned_worker = "jaeger_local"
            continue

        # Find eligible workers for the first required capability
        primary_cap = step.required_capabilities[0]
        eligible = registry.find_eligible(
            capability=primary_cap,
            data_sensitivity="personal",
        )

        if eligible:
            # Prefer local workers, then by proficiency
            eligible.sort(key=lambda w: (
                0 if w.data_location == "local" else 1,
                -next((c.proficiency for c in w.capabilities if c.capability_id == primary_cap), 0),
            ))
            step.assigned_worker = eligible[0].worker_id
        else:
            # Fallback to jaeger_local if no eligible worker found
            step.assigned_worker = "jaeger_local"

    return plan


def get_next_step(plan: Plan) -> Step | None:
    """Get the next step that should be executed.

    Returns the first PENDING step whose dependencies are all COMPLETED.
    """
    completed_ids = {s.step_id for s in plan.steps if s.status == StepStatus.COMPLETED}

    for step in plan.steps:
        if step.status != StepStatus.PENDING:
            continue
        if all(dep in completed_ids for dep in step.dependencies):
            return step

    return None


def advance_plan(plan: Plan, step_id: str, result: str, evaluation: str | None = None) -> Plan:
    """Mark a step as completed and advance the plan.

    If a step fails, increments retry count. If retries exhausted,
    marks step as FAILED. If all steps complete, marks plan as COMPLETED.
    """
    for step in plan.steps:
        if step.step_id == step_id:
            if evaluation == "fail" and step.retry_count < step.max_retries:
                step.retry_count += 1
                step.status = StepStatus.PENDING  # Retry
                step.result = result
                step.evaluation = evaluation
            else:
                step.status = StepStatus.COMPLETED if evaluation != "fail" else StepStatus.FAILED
                step.result = result
                step.evaluation = evaluation
            break

    # Update plan status
    all_completed = all(s.status == StepStatus.COMPLETED for s in plan.steps)
    any_failed = any(s.status == StepStatus.FAILED for s in plan.steps)

    if all_completed:
        plan.status = PlanStatus.COMPLETED
    elif any_failed:
        plan.status = PlanStatus.FAILED
    else:
        plan.status = PlanStatus.RUNNING

    plan.updated_at = time.time()
    return plan