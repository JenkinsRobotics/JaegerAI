"""Tests for Durable Background Work and Scheduling (Workstream 15).

Verifies Invariants:
1. Every durable task has: task_id, owning_agent, goal, state, run_history,
   retry_policy, cancellation, result, notification_policy, provenance.
2. Client disconnect does NOT terminate durable work.
3. Reconnection / UI restart reads durable progress from SqliteDurableTaskStore.
4. Process restart recovers orphaned in-flight tasks and resumes them.
5. Task cancellation stops work.
"""
from pathlib import Path
import tempfile
import time
import pytest

from jaeger_ai.core.tasks.manager import DurableTaskManager
from jaeger_ai.core.tasks.models import (
    DurableTask,
    RetryPolicy,
    TaskKind,
    TaskState,
)
from jaeger_ai.core.tasks.store import SqliteDurableTaskStore


@pytest.fixture
def task_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "durable_tasks.sqlite3"
        store = SqliteDurableTaskStore(db_path)
        mgr = DurableTaskManager(store, max_workers=2)
        yield mgr, store, db_path


def test_durable_task_lifecycle_and_client_disconnect(task_env):
    """Task launched by client continues to completion even if client disconnects."""
    mgr, store, _ = task_env

    # 1. Client submits durable background task
    task = mgr.submit_task(
        goal="Synthesize nightly report",
        owning_agent="agent:jaeger",
        kind=TaskKind.BACKGROUND_WORK,
        payload={"sections": ["finance", "deployments"]},
        provenance={"client_id": "client_web_101", "session_id": "sess_nightly"},
    )
    assert task.state == TaskState.QUEUED
    assert task.provenance["client_id"] == "client_web_101"

    # 2. Start execution asynchronously
    def background_work(t: DurableTask):
        time.sleep(0.1)
        return {"report_url": "s3://reports/nightly-2026.pdf", "status": "generated"}

    future = mgr.start_background_task(task.task_id, background_work)

    # 3. Simulate Client Disconnect! (client drops connection, loses future object)
    del future

    # Wait for completion in background pool
    time.sleep(0.3)

    # 4. Client reconnects / UI restarts and queries task from store
    refreshed = store.get_task(task.task_id)
    assert refreshed is not None
    assert refreshed.state == TaskState.COMPLETED
    assert refreshed.result["status"] == "generated"
    assert len(refreshed.run_history) == 1
    assert refreshed.run_history[0].status == "completed"


def test_crash_recovery_resumes_orphaned_tasks(task_env):
    """If process crashes while task is RUNNING, restart recovers and resumes it."""
    mgr, store, db_path = task_env

    # 1. Manually insert a task left in RUNNING state (simulating abrupt SIGKILL)
    task = mgr.submit_task("Process large dataset", "agent:jaeger")
    task.state = TaskState.RUNNING
    store.save_task(task)

    # Verify task is currently marked RUNNING
    assert store.get_task(task.task_id).state == TaskState.RUNNING

    # 2. Simulate Host Restart: create a fresh manager on the existing database
    new_store = SqliteDurableTaskStore(db_path)
    new_mgr = DurableTaskManager(new_store)

    completed_flag = False

    def recovery_runner(t: DurableTask):
        nonlocal completed_flag
        completed_flag = True
        return {"processed_rows": 1000}

    orphans = new_mgr.recover_and_resume_all(resumer_fn=recovery_runner)
    assert len(orphans) == 1
    assert orphans[0].task_id == task.task_id

    # Allow worker thread to run
    time.sleep(0.2)

    recovered = new_store.get_task(task.task_id)
    assert recovered.state == TaskState.COMPLETED
    assert recovered.result["processed_rows"] == 1000
    assert completed_flag is True


def test_task_cancellation(task_env):
    """User cancellation halts task and transitions state to CANCELLED."""
    mgr, store, _ = task_env

    task = mgr.submit_task("Continuous monitoring job", "agent:jaeger")
    cancelled = mgr.cancel_task(task.task_id, reason="Operator abort")
    assert cancelled is True

    refreshed = store.get_task(task.task_id)
    assert refreshed.state == TaskState.CANCELLED
    assert refreshed.cancellation == "Operator abort"


def test_task_retry_on_transient_failure(task_env):
    """Task fails once, retries within policy, then completes."""
    mgr, store, _ = task_env

    task = mgr.submit_task(
        "Flaky API fetch",
        "agent:jaeger",
        retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.1),
    )

    attempt = 0

    def flaky_work(t: DurableTask):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise ConnectionError("Temporary timeout")
        return {"data": "fetched"}

    # Attempt 1: Fails, gets re-queued
    future1 = mgr.start_background_task(task.task_id, flaky_work)
    time.sleep(0.2)

    t_after_fail = store.get_task(task.task_id)
    assert t_after_fail.state == TaskState.QUEUED
    assert t_after_fail.retry_policy.current_retries == 1

    # Attempt 2: Succeeds
    future2 = mgr.start_background_task(task.task_id, flaky_work)
    time.sleep(0.2)

    t_after_success = store.get_task(task.task_id)
    assert t_after_success.state == TaskState.COMPLETED
    assert t_after_success.result["data"] == "fetched"
    assert len(t_after_success.run_history) == 2
