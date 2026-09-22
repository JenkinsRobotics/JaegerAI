"""
ARES SI — Orchestrator.

Executes plans step by step, persisting state to the Journal database.
Supports retries, fallback workers, approval gates, and resumability.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from typing import Any

from .types import Plan, Step, PlanStatus, StepStatus, ContextBriefing, WorkerResult
from .planner import create_plan, assign_workers, get_next_step, advance_plan
from .context_compiler import compile_context, classify_intent
from .trust_engine import filter_briefing, log_disclosure, check_approval_required
from .worker_registry import get_registry


# ── Plan Persistence ────────────────────────────────────────────────────

_PLANS_DB = None


def _get_plans_db() -> sqlite3.Connection:
    """Get or create the plans database."""
    global _PLANS_DB
    if _PLANS_DB is not None:
        return _PLANS_DB

    from api.journal.paths import si_dir

    db_path = si_dir() / "plans.db"
    db = sqlite3.connect(str(db_path))
    db.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY,
            goal TEXT,
            status TEXT DEFAULT 'pending',
            conversation_id TEXT,
            created_at REAL,
            updated_at REAL,
            steps_json TEXT
        )
    """)
    db.commit()
    _PLANS_DB = db
    return _PLANS_DB


def save_plan(plan: Plan) -> None:
    """Persist a plan to the database."""
    db = _get_plans_db()
    steps_json = json.dumps([asdict(s) for s in plan.steps], default=str)
    db.execute("""
        INSERT OR REPLACE INTO plans (plan_id, goal, status, conversation_id, created_at, updated_at, steps_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        plan.plan_id,
        plan.goal,
        plan.status.value if isinstance(plan.status, PlanStatus) else plan.status,
        plan.conversation_id,
        plan.created_at,
        plan.updated_at,
        steps_json,
    ))
    db.commit()


def load_plan(plan_id: str) -> Plan | None:
    """Load a plan from the database."""
    db = _get_plans_db()
    row = db.execute(
        "SELECT plan_id, goal, status, conversation_id, created_at, updated_at, steps_json FROM plans WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    if not row:
        return None

    steps_data = json.loads(row[6])
    steps = [
        Step(
            step_id=s["step_id"],
            objective=s["objective"],
            dependencies=s.get("dependencies", []),
            required_capabilities=s.get("required_capabilities", []),
            assigned_worker=s.get("assigned_worker"),
            status=StepStatus(s.get("status", "pending")),
            result=s.get("result"),
            evaluation=s.get("evaluation"),
            retry_count=s.get("retry_count", 0),
            max_retries=s.get("max_retries", 2),
            requires_approval=s.get("requires_approval", False),
        )
        for s in steps_data
    ]

    return Plan(
        plan_id=row[0],
        goal=row[1],
        status=PlanStatus(row[2]),
        steps=steps,
        created_at=row[4],
        updated_at=row[5],
        conversation_id=row[3],
    )


def list_plans(status: str | None = None, limit: int = 20) -> list[dict]:
    """List plans, optionally filtered by status."""
    db = _get_plans_db()
    if status:
        rows = db.execute(
            "SELECT plan_id, goal, status, created_at, updated_at FROM plans WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT plan_id, goal, status, created_at, updated_at FROM plans ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"plan_id": r[0], "goal": r[1], "status": r[2], "created_at": r[3], "updated_at": r[4]}
        for r in rows
    ]


# ── Orchestration ──────────────────────────────────────────────────────

def orchestrate_request(
    user_message: str,
    conversation_id: str | None = None,
    local_only_mode: bool = False,
    si_name: str = "Assistant",
    owner_name: str = "User",
) -> dict:
    """Main orchestration entry point.

    1. Classifies intent
    2. Creates or continues a plan
    3. Compiles context
    4. Selects worker
    5. Returns execution info (actual worker execution happens via adapters)

    This function does NOT call the worker directly — it returns a
    structured briefing and worker assignment that the caller can
    dispatch to the appropriate adapter.
    """
    # 1. Classify intent
    intent, confidence = classify_intent(user_message)

    # 2. Determine if this needs a plan (simple vs complex)
    is_simple = intent in ("conversation",) and confidence >= 0.5

    # 3. Create plan
    plan = create_plan(
        goal=user_message,
        intent=intent,
        conversation_id=conversation_id,
        simple=is_simple,
    )

    # 4. Assign workers
    plan = assign_workers(plan)
    plan.status = PlanStatus.RUNNING

    # 5. Get next step
    next_step = get_next_step(plan)

    if not next_step:
        plan.status = PlanStatus.COMPLETED
        save_plan(plan)
        return {
            "plan_id": plan.plan_id,
            "intent": intent,
            "confidence": confidence,
            "status": "completed",
            "message": "No steps to execute",
        }

    # 6. Compile context for the assigned worker
    from .types import SIIdentity

    briefing = compile_context(
        user_message=user_message,
        target_worker_id=next_step.assigned_worker,
        token_budget=4000,
        local_only_mode=local_only_mode,
        si_identity=SIIdentity(name=si_name, owner_name=owner_name),
    )

    # 7. Check if approval is required
    needs_approval = check_approval_required(intent, "personal")
    if next_step.requires_approval:
        needs_approval = True

    if needs_approval:
        next_step.status = StepStatus.AWAITING_APPROVAL
        save_plan(plan)
        return {
            "plan_id": plan.plan_id,
            "intent": intent,
            "confidence": confidence,
            "status": "awaiting_approval",
            "step": {
                "step_id": next_step.step_id,
                "objective": next_step.objective,
                "assigned_worker": next_step.assigned_worker,
            },
            "briefing_tokens": briefing.total_tokens,
            "manifest_count": len(briefing.context_manifest),
            "needs_approval": True,
            "approval_reason": f"Action '{intent}' requires user approval",
        }

    # 8. Save and return execution info
    save_plan(plan)

    return {
        "plan_id": plan.plan_id,
        "intent": intent,
        "confidence": confidence,
        "status": "ready",
        "step": {
            "step_id": next_step.step_id,
            "objective": next_step.objective,
            "assigned_worker": next_step.assigned_worker,
            "required_capabilities": next_step.required_capabilities,
        },
        "briefing_tokens": briefing.total_tokens,
        "manifest_count": len(briefing.context_manifest),
        "total_steps": len(plan.steps),
        "needs_approval": False,
    }


def complete_step(
    plan_id: str,
    step_id: str,
    result: str,
    evaluation: str | None = None,
) -> dict:
    """Mark a step as completed and advance the plan.

    Returns the updated plan status and next step (if any).
    """
    plan = load_plan(plan_id)
    if not plan:
        return {"error": f"Plan {plan_id} not found"}

    plan = advance_plan(plan, step_id, result, evaluation)
    save_plan(plan)

    next_step = get_next_step(plan)

    return {
        "plan_id": plan.plan_id,
        "plan_status": plan.status.value,
        "completed_step": step_id,
        "next_step": {
            "step_id": next_step.step_id,
            "objective": next_step.objective,
            "assigned_worker": next_step.assigned_worker,
        } if next_step else None,
        "all_completed": plan.status == PlanStatus.COMPLETED,
    }


def cancel_plan(plan_id: str) -> dict:
    """Cancel a running plan."""
    plan = load_plan(plan_id)
    if not plan:
        return {"error": f"Plan {plan_id} not found"}

    plan.status = PlanStatus.CANCELLED
    for step in plan.steps:
        if step.status in (StepStatus.PENDING, StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL):
            step.status = StepStatus.CANCELLED

    save_plan(plan)
    return {"plan_id": plan_id, "status": "cancelled"}