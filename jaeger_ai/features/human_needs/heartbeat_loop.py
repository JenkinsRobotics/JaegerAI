"""Truth's awareness-driven Heartbeat <-> Human Needs operating loop.

Architecture invariant:
  Heartbeat -> Understand -> Prioritize -> Plan -> Act -> Verify -> Learn

The heartbeat is responsible for ongoing awareness, NOT continuous uncontrolled
activity. It reuses the authoritative ``SqliteDurableTaskStore``,
``SqliteWorldStore``, ``HumanNeedsStore``, and ``PolicyKernel``:
  - Never creates duplicate tasks for the same goal/opportunity.
  - Never pauses or interrupts an active user task.
  - Respects owner opt-outs (global or per-dimension) and quiet hours.
  - Blocks unauthorized or third-party-contact actions before execution.
  - Explicitly surfaces uncertainty when evidence is incomplete or conflicting.
  - Incorporates verified outcomes and owner corrections on subsequent beats.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
from pathlib import Path
import time
from typing import Any, Callable

from jaeger_ai.core.authority.kernel import AuthorityDecisionType, PolicyKernel, ProposedAction
from jaeger_ai.core.instance.instance import operator_state_root
from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskRunRecord, TaskState
from jaeger_ai.core.tasks.store import SqliteDurableTaskStore
from jaeger_ai.core.world.model import EpistemicProvenance
from jaeger_ai.core.world.store import SqliteWorldStore

from .policy import FlourishingDimension, SignalKind, evaluate_nudge, is_quiet_hours
from .store import HumanNeedsStore, default_human_needs_db


TaskExecutor = Callable[[DurableTask], dict[str, Any]]


@dataclass
class HeartbeatAwarenessReport:
    """Structured output of one Human Needs heartbeat awareness cycle."""

    checked_at: float
    proactive_enabled: bool
    in_quiet_hours: bool
    active_user_tasks: int
    goals_evaluated: int
    skipped_disabled_dimensions: list[str] = field(default_factory=list)
    skipped_duplicates: list[str] = field(default_factory=list)
    blocked_unauthorized: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[dict[str, Any]] = field(default_factory=list)
    created_opportunities: list[dict[str, Any]] = field(default_factory=list)
    admitted_tasks: list[dict[str, Any]] = field(default_factory=list)
    executed_outcomes: list[dict[str, Any]] = field(default_factory=list)
    digest_items: list[dict[str, Any]] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    incorporated_outcomes: int = 0
    silent_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dedupe_key(goal_id: str, action_spec: str) -> str:
    raw = f"{goal_id.strip()}|{action_spec.strip().lower()}"
    return "hn_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _default_task_db() -> Path:
    return operator_state_root() / "gateway_sessions.sqlite3"


def _default_world_db() -> Path:
    return operator_state_root() / "knowledge.sqlite3"


def _goal_evidence(world: SqliteWorldStore, goal: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Gather relevant claims and contradictions for a goal without guessing."""
    terms = [goal.get("goal_id") or "", goal.get("title") or ""]
    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for term in terms:
        clean = str(term).strip()
        if not clean:
            continue
        res = world.search_claims(clean[:80])
        for c in res.get("claims") or []:
            cid = c.get("claim_id")
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                matched.append(c)
    contradictions = world.find_contradictions()
    relevant_conflicts = [
        ctr for ctr in contradictions
        if any(
            str(goal.get("title") or "").lower() in str(ctr.get("subject") or "").lower()
            or str(ctr.get("subject") or "").lower() in str(goal.get("title") or "").lower()
            for _ in (0,)
        )
    ]
    if relevant_conflicts:
        uncertainty = f"Conflicting claims detected ({len(relevant_conflicts)}); verify before escalating."
    elif not matched:
        uncertainty = "No objective world-state observations linked yet; recommendation rests on user-stated goal only."
    else:
        verified = [c for c in matched if c.get("provenance") == EpistemicProvenance.VERIFIED.value]
        uncertainty = "" if verified else "Only unverified/told observations found; confirm factual baseline during execution."
    return matched[:10], relevant_conflicts, uncertainty


def _extract_proposed_action(goal: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
    """Derive a bounded, inspectable action proposal from a user's stated goal.

    Notes can optionally specify an explicit action hint such as
    ``[tool:write_file]`` or ``[contact_third_party]`` for tests and workflows;
    otherwise defaults to a read-only planning/progress check (``knowledge_query``).
    """
    notes = str(goal.get("notes") or "")
    title = str(goal.get("title") or "")
    combined = f"{title} {notes}".lower()
    contacts_third_party = "[contact_third_party]" in combined or "email my" in combined or "text my" in combined
    tool_name = "knowledge_query"
    arguments: dict[str, Any] = {"query": title[:120]}
    if "[tool:" in notes:
        after = notes.split("[tool:", 1)[1]
        if "]" in after:
            tool_name = after.split("]", 1)[0].strip() or "knowledge_query"
    if tool_name == "exec_command":
        arguments = {"command": notes.split("[cmd:", 1)[1].split("]", 1)[0].strip() if "[cmd:" in notes else "echo check"}
    elif tool_name == "write_file":
        arguments = {"path": notes.split("[path:", 1)[1].split("]", 1)[0].strip() if "[path:" in notes else "plan.md"}
    return tool_name, arguments, contacts_third_party


def run_human_needs_heartbeat(
    *,
    now: datetime | None = None,
    human_needs_db: Path | str | None = None,
    world_db: Path | str | None = None,
    task_db: Path | str | None = None,
    instance_root: Path | str | None = None,
    actor: str = "owner:heartbeat",
    executor: TaskExecutor | None = None,
    allow_task_creation_in_quiet_hours: bool = False,
) -> HeartbeatAwarenessReport:
    """Execute one bounded Human Needs awareness cycle on the standing heartbeat.

    Steps:
      1. Understand: load owner preferences, active goals, prior outcomes/interventions,
         world claims/contradictions, and currently running user tasks.
      2. Prioritize: rank active goals using owner priority + learned dimension weights,
         filtering out opted-out dimensions and already-handled dedupe keys.
      3. Authorize: verify policy guardrails (quiet hours, third-party contact, active
         user task protection) AND PolicyKernel decision before scheduling work.
      4. Plan/Act: admit at most ``max_proactive_tasks_per_beat`` durable task(s) into
         ``SqliteDurableTaskStore`` with explicit ``human_needs`` linkage.
      5. Verify/Learn: when ``executor`` is provided, execute authorized task, verify
         result, persist outcome + verified world claim, and update learning weights.
    """
    clock = now or datetime.now()
    hn_store = HumanNeedsStore(human_needs_db or default_human_needs_db())
    w_store = SqliteWorldStore(world_db or _default_world_db())
    t_store = SqliteDurableTaskStore(task_db or _default_task_db())

    prefs = hn_store.get_preferences()
    proactive_enabled = bool(prefs.get("proactive_enabled", True))
    quiet_start = int(prefs.get("quiet_start_hour", 22))
    quiet_end = int(prefs.get("quiet_end_hour", 7))
    quiet_now = is_quiet_hours(clock, quiet_start_hour=quiet_start, quiet_end_hour=quiet_end)
    disabled_dims = set(prefs.get("disabled_dimensions") or [])
    max_tasks = max(0, int(prefs.get("max_proactive_tasks_per_beat", 1)))
    dim_weights = dict(prefs.get("dimension_weights") or {})

    # Count non-proactive running tasks so proactive needs never interrupt live user work.
    running_tasks = t_store.list_tasks(state=TaskState.RUNNING)
    active_user_tasks = [
        t for t in running_tasks
        if (t.provenance or {}).get("source") != "human_needs_heartbeat"
    ]

    report = HeartbeatAwarenessReport(
        checked_at=clock.timestamp(),
        proactive_enabled=proactive_enabled,
        in_quiet_hours=quiet_now,
        active_user_tasks=len(active_user_tasks),
        goals_evaluated=0,
    )
    if not proactive_enabled:
        return report

    active_goals = [g for g in hn_store.list_goals(include_inactive=False) if g.get("status") == "active"]
    report.goals_evaluated = len(active_goals)
    if not active_goals:
        return report

    # Prioritize by owner priority (1=highest) modulated gently by learned dimension preference.
    def _rank(goal: dict[str, Any]) -> tuple[float, float]:
        prio = float(goal.get("priority", 3))
        weight = float(dim_weights.get(goal["dimension"], 1.0))
        return (prio / max(0.25, weight), -float(goal.get("updated_at") or 0.0))

    active_goals.sort(key=_rank)
    existing_tasks = t_store.list_tasks()
    tasks_by_dedupe = {
        str((t.provenance or {}).get("dedupe_key") or ""): t
        for t in existing_tasks
        if (t.provenance or {}).get("dedupe_key")
    }

    admitted_count = 0
    kernel = PolicyKernel()

    for goal in active_goals:
        gid = goal["goal_id"]
        dim = goal["dimension"]
        if dim in disabled_dims:
            report.skipped_disabled_dimensions.append(dim)
            continue

        prior_outcomes = hn_store.list_outcomes(goal_id=gid, limit=5)
        if prior_outcomes:
            report.incorporated_outcomes += len(prior_outcomes)

        tool_name, tool_args, contacts_third_party = _extract_proposed_action(goal)
        action_sig = f"{tool_name}:{goal['title']}:{goal.get('success_metric') or ''}"
        dkey = _dedupe_key(gid, action_sig)

        # Deduplication: never recreate an active, completed, or user-rejected intervention.
        existing_intv = hn_store.get_intervention_by_dedupe(dkey)
        existing_task = tasks_by_dedupe.get(dkey)
        if existing_intv is not None and existing_intv.get("status") in {
            "planned", "queued", "running", "completed_verified", "rejected", "blocked_unauthorized",
        }:
            report.skipped_duplicates.append(dkey)
            continue
        if existing_task is not None and existing_task.state in {
            TaskState.QUEUED, TaskState.RUNNING, TaskState.COMPLETED, TaskState.COMPLETED_VERIFIED,
        }:
            report.skipped_duplicates.append(dkey)
            continue

        evidence, conflicts, uncertainty = _goal_evidence(w_store, goal)
        if uncertainty:
            report.uncertainties.append({"goal_id": gid, "note": uncertainty, "conflicts": len(conflicts)})

        # Evaluate Human Flourishing delivery policy (quiet hours, active task, third-party contact, digest).
        nudge = evaluate_nudge(
            dim,
            active_task_running=bool(active_user_tasks),
            now=clock,
            contacts_third_party=contacts_third_party,
            user_authorized_contact=False,
            quiet_start_hour=quiet_start,
            quiet_end_hour=quiet_end,
        )
        if nudge.deliver == "suppress":
            hn_store.record_intervention(
                dkey, dim, goal_id=gid, status="blocked_unauthorized",
                evidence=evidence, uncertainty_note=nudge.reason,
            )
            report.blocked_unauthorized.append({
                "goal_id": gid, "tool": tool_name, "reason": nudge.reason, "policy": "human_needs_policy",
            })
            continue

        # During quiet hours (unless caller explicitly permits silent queued prep), defer to digest.
        if quiet_now and not allow_task_creation_in_quiet_hours:
            report.digest_items.append({
                "goal_id": gid,
                "dimension": dim,
                "title": goal["title"],
                "delivery": "daily_digest",
                "reason": nudge.reason,
                "uncertainty_note": uncertainty,
            })
            continue

        # PolicyKernel authority check BEFORE creating or executing any task.
        tier = "read_only" if tool_name in {"knowledge_query", "human_needs_summary"} else "write_local"
        decision = kernel.evaluate(
            ProposedAction(
                tool_name=tool_name,
                arguments=tool_args,
                session_id="heartbeat",
                actor=actor,
                tier=tier,
            ),
            instance_root=instance_root,
            dry_run=True,
        )
        if decision.decision != AuthorityDecisionType.ALLOW:
            hn_store.record_intervention(
                dkey, dim, goal_id=gid, status="blocked_unauthorized",
                evidence=evidence, uncertainty_note=decision.reason,
            )
            report.blocked_unauthorized.append({
                "goal_id": gid,
                "tool": tool_name,
                "decision": decision.decision.value,
                "reason": decision.reason,
                "policy": decision.policy_name,
            })
            continue

        if admitted_count >= max_tasks:
            # Bounded awareness: surface remaining goals in digest rather than flooding task queue.
            report.digest_items.append({
                "goal_id": gid, "dimension": dim, "title": goal["title"],
                "delivery": "daily_digest", "reason": "per-beat proactive task cap reached",
            })
            continue

        # Plan: create inferred opportunity + durable task atomically.
        opp = hn_store.propose_opportunity(
            title=f"Advance goal: {goal['title']}",
            dimension=dim,
            rationale=(
                f"User-stated priority {goal['priority']} goal ({dim}). "
                + (uncertainty or f"Backed by {len(evidence)} world observation(s).")
            ),
            goal_id=gid,
            proposed_action=f"{tool_name}({tool_args})",
            requires_authorization=False,
        )
        report.created_opportunities.append(opp)

        task_id = f"task_{dkey}"
        completion_condition = goal.get("success_metric") or f"Verified execution of {tool_name} for '{goal['title']}'"
        hn_meta = {
            "goal_id": gid,
            "opportunity_id": opp["opportunity_id"],
            "dimension": dim,
            "expected_benefit": f"Measurable progress toward '{goal['title']}'",
            "resource_cost": "low",
            "urgency": max(1, 6 - int(goal.get("priority", 3))),
            "evidence": [e.get("claim_id") for e in evidence if e.get("claim_id")],
            "completion_condition": completion_condition,
            "uncertainty_note": uncertainty,
        }
        task = DurableTask(
            task_id=task_id,
            owning_agent="truth",
            agent_id="truth",
            goal=f"[Human Needs:{dim}] {goal['title']}",
            kind=TaskKind.AUTOMATION,
            state=TaskState.QUEUED,
            payload={"tool_name": tool_name, "arguments": tool_args, "goal_id": gid},
            provenance={
                "source": "human_needs_heartbeat",
                "goal_id": gid,
                "opportunity_id": opp["opportunity_id"],
                "dedupe_key": dkey,
                "actor": actor,
            },
            human_needs=hn_meta,
        )
        admitted_task, already_existed = t_store.admit_task(task)
        if already_existed:
            report.skipped_duplicates.append(dkey)
            continue

        intv, _ = hn_store.record_intervention(
            dkey, dim, goal_id=gid, opportunity_id=opp["opportunity_id"],
            task_id=admitted_task.task_id, status="queued",
            evidence=evidence, uncertainty_note=uncertainty,
        )
        report.admitted_tasks.append(admitted_task.to_dict())
        admitted_count += 1

        # Act & Verify when an executor is wired for this cycle.
        if executor is not None:
            run_rec = TaskRunRecord(run_id=f"run_{dkey}", started_at=time.time(), status="running")
            admitted_task.state = TaskState.RUNNING
            admitted_task.run_history.append(run_rec)
            t_store.save_task(admitted_task)
            try:
                exec_res = executor(admitted_task) or {}
                verified_ok = bool(exec_res.get("ok")) and bool(exec_res.get("verified", True))
                evidence_ref = str(exec_res.get("evidence_ref") or f"task:{admitted_task.task_id}")
                summary_txt = str(exec_res.get("summary") or f"Completed authorized work for '{goal['title']}'")
            except Exception as exc:  # noqa: BLE001
                verified_ok = False
                exec_res = {"ok": False, "error": str(exc)}
                evidence_ref = f"task:{admitted_task.task_id}"
                summary_txt = f"Intervention failed: {exc}"

            run_rec.completed_at = time.time()
            if verified_ok:
                run_rec.status = "completed"
                admitted_task.state = TaskState.COMPLETED_VERIFIED
                admitted_task.result = exec_res
                t_store.save_task(admitted_task)
                outcome = hn_store.record_outcome(
                    summary_txt,
                    goal_id=gid,
                    opportunity_id=opp["opportunity_id"],
                    signal_kind=SignalKind.OBJECTIVE_MEASURE,
                    metric_name=str(exec_res.get("metric_name") or goal.get("success_metric") or "task_completion"),
                    metric_before=str(exec_res.get("metric_before") or "pending"),
                    metric_after=str(exec_res.get("metric_after") or "verified"),
                    evidence_ref=evidence_ref,
                )
                hn_store.decide_opportunity(opp["opportunity_id"], "completed", user_feedback="verified_by_heartbeat")
                hn_store.update_intervention(
                    intv["intervention_id"], status="completed_verified", outcome_id=outcome["outcome_id"],
                )
                w_store.record_claim(
                    subject=goal["title"],
                    predicate="latest_verified_outcome",
                    value=summary_txt,
                    provenance=EpistemicProvenance.VERIFIED,
                    confidence=1.0,
                    source_id=evidence_ref,
                )
                report.executed_outcomes.append(outcome)
            else:
                run_rec.status = "failed"
                run_rec.error = str(exec_res.get("error") or summary_txt)
                admitted_task.state = TaskState.FAILED
                admitted_task.error = run_rec.error
                t_store.save_task(admitted_task)
                hn_store.update_intervention(
                    intv["intervention_id"], status="failed", uncertainty_note=run_rec.error,
                )
                report.executed_outcomes.append({"ok": False, "task_id": admitted_task.task_id, "error": run_rec.error})

        # Appropriate notification vs daily digest routing.
        item = {
            "goal_id": gid,
            "task_id": admitted_task.task_id,
            "dimension": dim,
            "title": goal["title"],
            "delivery": nudge.deliver,
            "uncertainty_note": uncertainty,
        }
        if nudge.deliver == "gentle_nudge" and not quiet_now and not active_user_tasks:
            report.notifications.append(item)
        else:
            report.digest_items.append(item)

    report.silent_ok = not (report.admitted_tasks or report.notifications)
    return report
