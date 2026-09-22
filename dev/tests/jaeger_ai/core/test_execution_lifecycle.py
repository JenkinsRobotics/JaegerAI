"""Tests for Canonical Work Lifecycle & Execution Model Consolidation (UPAA Workstream 2).

Proves:
1. One canonical lifecycle across states:
   CREATED -> QUEUED -> RUNNING -> WAITING_FOR_APPROVAL -> RUNNING -> VERIFYING -> COMPLETED
   or FAILED / CANCELLED / INTERRUPTED / RECOVERABLE.
2. Illegal state jumps raise LifecycleTransitionError.
3. One request ID maps to one durable run.
4. Suspended approval state is durable (survives process restart without thread lock).
5. Cancellation is deterministic.
6. Process death (SIGKILL simulation) moves runs to INTERRUPTED.
7. Effect ledger idempotency prevents duplicate side effects after recovery.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import pytest

from jaeger_ai.core.runtime.lifecycle import (
    ALLOWED_TRANSITIONS,
    LifecycleTransitionError,
    RunLifecycleCoordinator,
    WorkState,
    normalize_state,
    validate_transition,
)
from jaeger_agent.cognition.sqlite_runs import SqliteEffectLedger, SqliteRunStore
from jaeger_agent.cognition.sqlite_commitments import SqliteCommitmentStore
from jaeger_agent.memory import sqlite_store


@pytest.fixture
def isolated_run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide isolated SQLite storage for runs, commitments, and effects."""
    monkeypatch.setenv("JAEGER_STATE_DIR", str(tmp_path))
    sqlite_store.bind(SimpleNamespace(memory_dir=tmp_path))
    commits = SqliteCommitmentStore()
    runs = SqliteRunStore()
    ledger = SqliteEffectLedger()
    coordinator = RunLifecycleCoordinator(run_store=runs)
    return {
        "dir": tmp_path,
        "commits": commits,
        "runs": runs,
        "ledger": ledger,
        "coordinator": coordinator,
    }


def test_canonical_state_machine_transitions():
    """Verify all canonical transitions flow legally through the state machine."""
    # Forward happy path
    validate_transition("r1", WorkState.CREATED, WorkState.QUEUED)
    validate_transition("r1", WorkState.QUEUED, WorkState.RUNNING)
    validate_transition("r1", WorkState.RUNNING, WorkState.WAITING_FOR_APPROVAL)
    validate_transition("r1", WorkState.WAITING_FOR_APPROVAL, WorkState.RUNNING)
    validate_transition("r1", WorkState.RUNNING, WorkState.VERIFYING)
    validate_transition("r1", WorkState.VERIFYING, WorkState.COMPLETED)

    # Alternate abort/interrupted branches
    validate_transition("r2", WorkState.RUNNING, WorkState.INTERRUPTED)
    validate_transition("r2", WorkState.INTERRUPTED, WorkState.RECOVERABLE)
    validate_transition("r2", WorkState.RECOVERABLE, WorkState.RUNNING)
    validate_transition("r2", WorkState.RUNNING, WorkState.FAILED)
    validate_transition("r2", WorkState.FAILED, WorkState.RECOVERABLE)

    # Cancellation
    validate_transition("r3", WorkState.CREATED, WorkState.CANCELLED)
    validate_transition("r4", WorkState.QUEUED, WorkState.CANCELLED)
    validate_transition("r5", WorkState.RUNNING, WorkState.CANCELLED)
    validate_transition("r6", WorkState.WAITING_FOR_APPROVAL, WorkState.CANCELLED)


def test_illegal_state_transitions_raise():
    """Illegal transitions must raise LifecycleTransitionError fail-closed."""
    # Direct illegal jump: CREATED -> COMPLETED
    with pytest.raises(LifecycleTransitionError):
        validate_transition("err1", WorkState.CREATED, WorkState.COMPLETED)

    # Illegal jump: COMPLETED -> RUNNING (terminal is final)
    with pytest.raises(LifecycleTransitionError):
        validate_transition("err2", WorkState.COMPLETED, WorkState.RUNNING)

    # Illegal jump: CANCELLED -> RUNNING
    with pytest.raises(LifecycleTransitionError):
        validate_transition("err3", WorkState.CANCELLED, WorkState.RUNNING)


def test_request_id_maps_to_durable_run(isolated_run_env):
    """One request ID maps to one durable run with request provenance."""
    coord: RunLifecycleCoordinator = isolated_run_env["coordinator"]
    commits: SqliteCommitmentStore = isolated_run_env["commits"]

    commitment = commits.create("test-intention", kind="goal")
    req_id = "req_9981_prod"

    run = coord.create_run(
        commitment.id,
        request_id=req_id,
        provider="ollama:kimi",
        owner_pid=os.getpid(),
    )

    assert run.id
    assert run.commitment_id == commitment.id
    assert run.payload.get("request_id") == req_id
    assert run.state == WorkState.CREATED.value

    # Advance through queue to running
    coord.advance(run.id, WorkState.QUEUED)
    assert isolated_run_env["runs"].get(run.id).state == WorkState.QUEUED.value

    coord.advance(run.id, WorkState.RUNNING)
    assert isolated_run_env["runs"].get(run.id).state == WorkState.RUNNING.value


def test_durable_approval_suspension_and_resume(isolated_run_env):
    """Run suspended for approval is durable in SQLite and resumes when approved."""
    coord: RunLifecycleCoordinator = isolated_run_env["coordinator"]
    commits: SqliteCommitmentStore = isolated_run_env["commits"]
    runs: SqliteRunStore = isolated_run_env["runs"]

    commitment = commits.create("approval-task", kind="goal")
    run = coord.create_run(commitment.id, request_id="req_app_1")
    coord.advance(run.id, WorkState.RUNNING)

    # Suspend for human approval
    app_id = "approval_xyz789"
    coord.suspend_for_approval(run.id, app_id, reason="file_overwrite_confirmation")

    persisted = runs.get(run.id)
    assert persisted.state == WorkState.WAITING_FOR_APPROVAL.value
    assert persisted.wake_key == f"approval:{app_id}"

    # Simulate process restart / reload from disk
    reloaded_runs = SqliteRunStore()
    reloaded_coord = RunLifecycleCoordinator(run_store=reloaded_runs)
    assert reloaded_runs.get(run.id).state == WorkState.WAITING_FOR_APPROVAL.value

    # Resume approval granted
    woken = reloaded_coord.resume_from_approval(app_id, approved=True)
    assert any(r.id == run.id for r in woken)

    resumed_run = reloaded_runs.get(run.id)
    assert normalize_state(resumed_run.state) == WorkState.RUNNING


def test_deterministic_cancellation(isolated_run_env):
    """Cancellation transitions run to CANCELLED and disallows further transitions."""
    coord: RunLifecycleCoordinator = isolated_run_env["coordinator"]
    commits: SqliteCommitmentStore = isolated_run_env["commits"]
    runs: SqliteRunStore = isolated_run_env["runs"]

    commitment = commits.create("cancel-task", kind="goal")
    run = coord.create_run(commitment.id, request_id="req_cancel_1")
    coord.advance(run.id, WorkState.QUEUED)

    coord.advance(run.id, WorkState.CANCELLED, reason="user_clicked_stop")
    cancelled_run = runs.get(run.id)
    assert cancelled_run.state == WorkState.CANCELLED.value

    # Further transition is strictly disallowed
    with pytest.raises(LifecycleTransitionError):
        coord.advance(run.id, WorkState.RUNNING)


def test_sigkill_process_recovery_leaves_interrupted_run(isolated_run_env):
    """Orphaned runs owned by dead PIDs transition deterministically to INTERRUPTED."""
    coord: RunLifecycleCoordinator = isolated_run_env["coordinator"]
    commits: SqliteCommitmentStore = isolated_run_env["commits"]
    runs: SqliteRunStore = isolated_run_env["runs"]

    commitment = commits.create("sigkill-task", kind="goal")
    # Simulate a run claimed by a PID that died
    dead_pid = 999998
    run = coord.create_run(commitment.id, request_id="req_dead_pid", owner_pid=dead_pid)
    coord.advance(run.id, WorkState.RUNNING)

    orphaned = coord.recover_orphaned_runs(is_alive=lambda pid: False)
    assert run.id in orphaned

    recovered_run = runs.get(run.id)
    assert recovered_run.state == WorkState.INTERRUPTED.value
    assert recovered_run.reason == "owner_pid_terminated"


def test_effect_ledger_prevents_duplicate_effects_after_recovery(isolated_run_env):
    """Side effects are claimed once in EffectLedger, preventing duplication on crash recovery."""
    ledger: SqliteEffectLedger = isolated_run_env["ledger"]
    run_id = "run_safe_effects"
    effect_key = f"{run_id}:send_webhook:http://example.com/api"

    call_count = 0

    def _external_mutation():
        nonlocal call_count
        call_count += 1
        return {"status": 200, "tx_id": "tx_8819"}

    # First execution: claims and records effect
    res1, executed1 = ledger.once(effect_key, "send_webhook", _external_mutation, run_id=run_id)
    assert executed1 is True
    assert res1["tx_id"] == "tx_8819"
    assert call_count == 1

    # Simulate crash recovery where resumed run re-executes the step
    res2, executed2 = ledger.once(effect_key, "send_webhook", _external_mutation, run_id=run_id)
    assert executed2 is False  # NOT executed again!
    assert res2["tx_id"] == "tx_8819"
    assert call_count == 1  # External mutation was strictly invoked once!
