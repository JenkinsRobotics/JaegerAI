"""Required Heartbeat Acceptance Test (§1.6) for Human Needs <-> Heartbeat integration.

Verifies the complete operating loop end to end:
  User goal -> persistent memory -> heartbeat detects opportunity ->
  authorized task created -> autonomous execution -> verified result ->
  outcome recorded -> next heartbeat incorporates result.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import yaml

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.instance.schemas import Config, dump_yaml
from jaeger_ai.core.tasks.models import DurableTask, TaskKind, TaskState
from jaeger_ai.core.tasks.store import SqliteDurableTaskStore
from jaeger_ai.core.world.model import EpistemicProvenance
from jaeger_ai.core.world.store import SqliteWorldStore
from jaeger_ai.features.human_needs.heartbeat_loop import run_human_needs_heartbeat
from jaeger_ai.features.human_needs.store import HumanNeedsStore


def _make_isolated_env(tmp_path: Path, *, autonomy: str = "auto", shell_mode: str = "confirm"):
    inst = tmp_path / "instances" / "truth_test"
    layout = InstanceLayout(root=inst)
    layout.ensure_dirs()
    cfg = Config(instance_name="truth_test", model={"model_path": "unconfigured"})
    cfg.automation.autonomy = autonomy
    cfg.permissions.mode = "allow" if autonomy == "auto" else "confirm"
    dump_yaml(layout.config_path, cfg)
    (inst / "authority_policy.yaml").write_text(
        yaml.safe_dump({"shell": {"risk_mode": shell_mode}, "filesystem": {"write": True}, "git": {"push": False}}),
        encoding="utf-8",
    )
    return (
        inst,
        tmp_path / "human_needs.sqlite3",
        tmp_path / "knowledge.sqlite3",
        tmp_path / "gateway_sessions.sqlite3",
    )


def test_complete_heartbeat_cycle_no_duplicates_and_restart_persistence(tmp_path: Path):
    inst, hn_db, w_db, t_db = _make_isolated_env(tmp_path)
    daytime = datetime(2026, 11, 19, 14, 0, 0)

    # 1. Isolated test user sets a goal and persistent world observation
    hn = HumanNeedsStore(hn_db)
    goal = hn.add_goal(
        "Build Python robotics control fluency",
        "competence_esteem",
        priority=1,
        notes="[tool:write_file][path:study_plan.md] Prepare a concise 2-week kinematics exercise checklist.",
        success_metric="study_plan.md created and verified",
    )
    world = SqliteWorldStore(w_db)
    world.record_claim(
        "Build Python robotics control fluency",
        "baseline_observation",
        "User completed inverse kinematics module 1",
        EpistemicProvenance.VERIFIED,
        source_id="owner_log",
    )

    executed_artifacts: list[Path] = []

    def _autonomous_executor(task: DurableTask) -> dict:
        out_file = tmp_path / "study_plan.md"
        out_file.write_text("# Kinematics Study Plan\n- Week 1: DH parameters\n- Week 2: Jacobian control\n", encoding="utf-8")
        executed_artifacts.append(out_file)
        assert out_file.is_file() and "Jacobian" in out_file.read_text(encoding="utf-8")
        return {
            "ok": True,
            "verified": True,
            "summary": "Created verified 2-week kinematics study plan",
            "metric_name": "study_plan_created",
            "metric_before": "0",
            "metric_after": "1",
            "evidence_ref": str(out_file),
        }

    # 2. First heartbeat: detects opportunity -> authorizes -> creates durable task -> executes -> verifies -> records outcome
    r1 = run_human_needs_heartbeat(
        now=daytime, human_needs_db=hn_db, world_db=w_db, task_db=t_db,
        instance_root=inst, actor="owner:heartbeat", executor=_autonomous_executor,
    )
    assert r1.goals_evaluated == 1
    assert len(r1.created_opportunities) == 1
    assert len(r1.admitted_tasks) == 1
    assert r1.admitted_tasks[0]["human_needs"]["goal_id"] == goal["goal_id"]
    assert r1.admitted_tasks[0]["human_needs"]["dimension"] == "competence_esteem"
    assert len(r1.executed_outcomes) == 1
    assert len(executed_artifacts) == 1 and executed_artifacts[0].exists()
    assert len(r1.notifications) == 1

    # 3. Simulate restart (brand-new SQLite store instances) and run SECOND heartbeat:
    #    - Goal, task, outcome, and verified world claim survive restart.
    #    - Next heartbeat incorporates prior outcome and creates ZERO duplicate tasks!
    r2 = run_human_needs_heartbeat(
        now=datetime(2026, 11, 19, 14, 30, 0),
        human_needs_db=hn_db, world_db=w_db, task_db=t_db,
        instance_root=inst, actor="owner:heartbeat", executor=_autonomous_executor,
    )
    assert r2.incorporated_outcomes >= 1
    assert len(r2.admitted_tasks) == 0
    assert len(r2.skipped_duplicates) == 1
    assert len(executed_artifacts) == 1  # Never re-executed!
    assert r2.silent_ok is True

    # Confirm persisted state after restart
    reopened_hn = HumanNeedsStore(hn_db)
    reopened_tasks = SqliteDurableTaskStore(t_db)
    reopened_world = SqliteWorldStore(w_db)
    assert len(reopened_hn.list_goals()) == 1
    assert len(reopened_hn.list_outcomes(goal_id=goal["goal_id"])) == 1
    tasks = reopened_tasks.list_tasks()
    assert len(tasks) == 1 and tasks[0].state == TaskState.COMPLETED_VERIFIED
    claims = reopened_world.query_claims("Build Python robotics control fluency")
    assert any(c.predicate == "latest_verified_outcome" and c.provenance == EpistemicProvenance.VERIFIED for c in claims)


def test_quiet_hours_opt_outs_active_task_protection_and_unauthorized_blocking(tmp_path: Path):
    inst, hn_db, w_db, t_db = _make_isolated_env(tmp_path, shell_mode="deny")
    hn = HumanNeedsStore(hn_db)

    # Goal 1: triggers unauthorized third-party contact -> must be blocked
    hn.add_goal("Check in with Sarah", "belonging", priority=1, notes="[contact_third_party] Email my friend Sarah")
    # Goal 2: tries shell when shell.risk_mode=deny -> must be blocked by PolicyKernel
    hn.add_goal("Clean temp logs", "security", priority=1, notes="[tool:exec_command][cmd:ls /tmp]")
    # Goal 3: valid goal with no world observations yet -> must report uncertainty honestly
    g_uncertain = hn.add_goal("Save emergency reserve", "security", priority=2, notes="Track monthly savings progress")

    # A. Quiet hours (23:30): valid goal routes to digest, zero tasks created; unauthorized still blocked
    r_quiet = run_human_needs_heartbeat(
        now=datetime(2026, 11, 19, 23, 30, 0),
        human_needs_db=hn_db, world_db=w_db, task_db=t_db, instance_root=inst,
    )
    assert r_quiet.in_quiet_hours is True
    assert len(r_quiet.admitted_tasks) == 0
    assert any(d["goal_id"] == g_uncertain["goal_id"] for d in r_quiet.digest_items)
    assert any(b["policy"] == "human_needs_policy" for b in r_quiet.blocked_unauthorized)
    assert any(u["goal_id"] == g_uncertain["goal_id"] and "No objective" in u["note"] for u in r_quiet.uncertainties)

    # B. Daytime: PolicyKernel blocks shell.risk_mode=deny; active user task routes valid nudge to digest
    t_store = SqliteDurableTaskStore(t_db)
    user_task = DurableTask(
        task_id="user_live_1", owning_agent="truth", goal="Run user build",
        kind=TaskKind.BACKGROUND_WORK, state=TaskState.RUNNING,
    )
    assert user_task.human_needs is None  # Simple user tasks never require human_needs label
    t_store.save_task(user_task)

    r_day = run_human_needs_heartbeat(
        now=datetime(2026, 11, 19, 13, 0, 0),
        human_needs_db=hn_db, world_db=w_db, task_db=t_db, instance_root=inst,
    )
    assert r_day.active_user_tasks == 1
    assert any(b["policy"] == "commissioning_authority" for b in r_day.blocked_unauthorized)
    assert len(r_day.notifications) == 0  # Active user task is never interrupted!
    assert t_store.get_task("user_live_1").state == TaskState.RUNNING

    # C. Dimension opt-out + global opt-out persist across reopen
    hn.update_preferences({"disabled_dimensions": ["security"]})
    r_dim_off = run_human_needs_heartbeat(
        now=datetime(2026, 11, 19, 15, 0, 0),
        human_needs_db=hn_db, world_db=w_db, task_db=t_db, instance_root=inst,
    )
    assert "security" in r_dim_off.skipped_disabled_dimensions

    HumanNeedsStore(hn_db).update_preferences({"proactive_enabled": False})
    r_global_off = run_human_needs_heartbeat(
        now=datetime(2026, 11, 19, 16, 0, 0),
        human_needs_db=hn_db, world_db=w_db, task_db=t_db, instance_root=inst,
    )
    assert r_global_off.proactive_enabled is False
    assert r_global_off.goals_evaluated == 0


def test_owner_review_correction_and_rejection_learning(tmp_path: Path):
    inst, hn_db, w_db, t_db = _make_isolated_env(tmp_path)
    hn = HumanNeedsStore(hn_db)
    goal = hn.add_goal("Improve sleep routine", "physical_wellbeing", priority=2)
    opp = hn.propose_opportunity(
        "Shift bedtime earlier", "physical_wellbeing", "Inferred from late commits", goal_id=goal["goal_id"]
    )
    # Owner reviews and corrects the inferred rationale
    corrected = hn.correct_opportunity(
        opp["opportunity_id"],
        rationale="Owner prefers steady wake time rather than fixed bedtime",
        user_feedback="Focus on wake-time consistency",
    )
    assert "wake time" in corrected["rationale"]
    assert corrected["user_feedback"] == "Focus on wake-time consistency"

    # Owner rejects -> learned weight for dimension decreases and persists
    before_w = float(hn.get_preferences().get("dimension_weights", {}).get("physical_wellbeing", 1.0))
    hn.decide_opportunity(opp["opportunity_id"], "rejected", user_feedback="Not needed this week")
    after_w = float(HumanNeedsStore(hn_db).get_preferences()["dimension_weights"]["physical_wellbeing"])
    assert after_w < before_w
