"""Agent tools for the user-owned Human Needs & Flourishing Engine.

Respects all policy guardrails in ``jaeger_ai.features.human_needs.policy``:
quiet hours (22:00-07:00), never interrupting active tasks, digest-only routing
for belonging/self-transcendence, and never contacting third parties without
explicit authorization.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .policy import FlourishingDimension, SignalKind, evaluate_nudge, is_quiet_hours
from .store import HumanNeedsStore


def human_needs_summary(
    include_inactive: bool = False,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return user-owned goals, proposed opportunities, outcomes, and quiet-hours status."""
    store = HumanNeedsStore(db_path)
    return {
        "ok": True,
        "quiet_hours_active": is_quiet_hours(),
        "goals": store.list_goals(include_inactive=bool(include_inactive)),
        "opportunities": store.list_opportunities(),
        "outcomes": store.list_outcomes(limit=25),
    }


def human_needs_add_goal(
    title: str,
    dimension: str,
    priority: int = 3,
    notes: str = "",
    success_metric: str = "",
    signal_kind: str = "user_preference",
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Record a user-owned flourishing goal."""
    store = HumanNeedsStore(db_path)
    try:
        goal = store.add_goal(
            title=title,
            dimension=FlourishingDimension(str(dimension).strip().lower()),
            signal_kind=SignalKind(str(signal_kind or "user_preference").strip().lower()),
            priority=int(priority),
            notes=notes,
            success_metric=success_metric,
        )
        return {"ok": True, "goal": goal}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def human_needs_propose_opportunity(
    title: str,
    dimension: str,
    rationale: str,
    goal_id: str = "",
    proposed_action: str = "",
    contacts_third_party: bool = False,
    active_task_running: bool = False,
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Propose a non-intrusive opportunity gated by Human Flourishing policy."""
    try:
        dim = FlourishingDimension(str(dimension).strip().lower())
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    policy = evaluate_nudge(
        dim,
        active_task_running=bool(active_task_running),
        contacts_third_party=bool(contacts_third_party),
        user_authorized_contact=False,
    )
    if policy.deliver == "suppress":
        return {
            "ok": False,
            "suppressed": True,
            "nudge_policy": asdict(policy),
            "error": policy.reason,
        }

    store = HumanNeedsStore(db_path)
    try:
        opp = store.propose_opportunity(
            title=title,
            dimension=dim,
            rationale=rationale,
            goal_id=(goal_id or "").strip() or None,
            proposed_action=proposed_action,
            requires_authorization=True,
        )
        return {"ok": True, "opportunity": opp, "nudge_policy": asdict(policy)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def human_needs_record_outcome(
    summary: str,
    goal_id: str = "",
    opportunity_id: str = "",
    metric_name: str = "",
    metric_before: str = "",
    metric_after: str = "",
    evidence_ref: str = "",
    signal_kind: str = "objective_measure",
    *,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Record a measurable outcome linked to a user goal or opportunity."""
    store = HumanNeedsStore(db_path)
    try:
        outcome = store.record_outcome(
            summary=summary,
            goal_id=(goal_id or "").strip() or None,
            opportunity_id=(opportunity_id or "").strip() or None,
            signal_kind=SignalKind(str(signal_kind or "objective_measure").strip().lower()),
            metric_name=metric_name,
            metric_before=metric_before,
            metric_after=metric_after,
            evidence_ref=evidence_ref,
        )
        return {"ok": True, "outcome": outcome}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
