"""Tests for standalone jaeger-workflows durable SQLite DAG engine."""

from __future__ import annotations

import pytest

from jaeger_workflows import (
    StepStatus,
    WorkflowEngine,
    WorkflowError,
    WorkflowStep,
)


def test_dag_executes_in_order_and_resumes_durably(tmp_path):
    db = tmp_path / "workflows.sqlite3"
    engine = WorkflowEngine(db)
    run = engine.create_run(
        "youtube-episode",
        [
            WorkflowStep(id="script", name="Draft script", action="draft", idempotent=True),
            WorkflowStep(id="voice", name="Render voiceover", action="tts", depends_on=("script",), idempotent=True),
            WorkflowStep(id="publish", name="Export final video", action="render", depends_on=("voice",), requires_approval=True),
        ],
        context={"topic": "JaegerAI"},
    )
    executed: list[str] = []

    def executor(step: WorkflowStep, ctx: dict):
        executed.append(step.id)
        return {"ran": step.id, "prev": sorted((ctx.get("outputs") or {}).keys())}

    # First advance runs script -> voice, then pauses on publish approval gate.
    paused = engine.advance(run.run_id, executor)
    assert paused.status == StepStatus.WAITING_APPROVAL.value
    assert executed == ["script", "voice"]
    assert paused.records["voice"].output["prev"] == ["script"]

    # Simulate full process restart with a brand-new engine pointing at the same SQLite DB.
    restarted = WorkflowEngine(db)
    restarted.approve_step(run.run_id, "publish", approved=True, note="owner approved")
    done = restarted.advance(run.run_id, executor)
    assert done.status == StepStatus.COMPLETED.value
    # Already-completed steps must NEVER re-run on resume!
    assert executed == ["script", "voice", "publish"]
    assert done.records["publish"].output["prev"] == ["script", "voice"]


def test_fail_closed_retry_law_only_retries_idempotent_steps(tmp_path):
    engine = WorkflowEngine(tmp_path / "wf.sqlite3")
    # Non-idempotent step with max_retries=3 must still execute AT MOST ONCE.
    run1 = engine.create_run(
        "non-idempotent-send",
        [WorkflowStep(id="send", name="Send mail", idempotent=False, max_retries=3)],
    )
    calls = 0

    def fail_always(_step, _ctx):
        nonlocal calls
        calls += 1
        raise RuntimeError("network hiccup")

    res1 = engine.advance(run1.run_id, fail_always)
    assert res1.status == StepStatus.FAILED.value
    assert calls == 1

    # Idempotent step retries up to max_retries and recovers.
    run2 = engine.create_run(
        "idempotent-probe",
        [WorkflowStep(id="probe", name="Probe", idempotent=True, max_retries=3)],
    )
    attempts = 0

    def flaky(_step, _ctx):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("503")
        return {"ok": True}

    res2 = engine.advance(run2.run_id, flaky)
    assert res2.status == StepStatus.COMPLETED.value
    assert attempts == 3


def test_cycle_detection_and_rejection(tmp_path):
    engine = WorkflowEngine(tmp_path / "wf.sqlite3")
    with pytest.raises(WorkflowError, match="cycle"):
        engine.create_run(
            "bad",
            [
                WorkflowStep(id="a", name="A", depends_on=("b",)),
                WorkflowStep(id="b", name="B", depends_on=("a",)),
            ],
        )
    run = engine.create_run("gated", [WorkflowStep(id="wipe", name="Delete", requires_approval=True)])
    engine.advance(run.run_id, lambda s, c: None)
    denied = engine.approve_step(run.run_id, "wipe", approved=False, note="no")
    assert denied.status == StepStatus.FAILED.value
    assert "approval denied" in denied.error


def test_interrupted_running_step_reconciliation_and_receipt_provenance(tmp_path):
    engine = WorkflowEngine(tmp_path / "wf.sqlite3")
    # 1. Non-idempotent step interrupted mid-run must fail closed to outcome_unknown
    run_mut = engine.create_run("mut", [WorkflowStep(id="send", name="Send", idempotent=False)])
    engine.checkpoint_step(run_mut.run_id, "send", status=StepStatus.RUNNING.value)
    called = []
    after_mut = engine.advance(run_mut.run_id, lambda s, c: called.append(s.id))
    assert after_mut.status == StepStatus.OUTCOME_UNKNOWN.value
    assert after_mut.records["send"].status == StepStatus.OUTCOME_UNKNOWN.value
    assert called == []  # never blindly replayed!

    # 2. Idempotent step interrupted mid-run safely resets & resumes
    run_idem = engine.create_run("idem", [WorkflowStep(id="fetch", name="Fetch", idempotent=True)])
    engine.checkpoint_step(run_idem.run_id, "fetch", status=StepStatus.RUNNING.value)
    after_idem = engine.advance(run_idem.run_id, lambda s, c: {"rows": 5})
    assert after_idem.status == StepStatus.COMPLETED.value
    assert after_idem.records["fetch"].output == {"rows": 5}

    # 3. Receipt provenance distinguishes self-reported vs tool-receipt checkpoints
    run_rec = engine.create_run("rec", [WorkflowStep(id="s1", name="S1"), WorkflowStep(id="s2", name="S2")])
    r1 = engine.checkpoint_step(run_rec.run_id, "s1", status=StepStatus.COMPLETED.value)
    assert r1.records["s1"].verified is False
    assert r1.records["s1"].receipt_source == "self_reported"
    r2 = engine.checkpoint_step(
        run_rec.run_id,
        "s2",
        status=StepStatus.COMPLETED.value,
        receipt={"ok": True, "moved_count": 4},
        receipt_source="tool_receipt",
    )
    assert r2.records["s2"].verified is True
    assert r2.records["s2"].receipt == {"ok": True, "moved_count": 4}
