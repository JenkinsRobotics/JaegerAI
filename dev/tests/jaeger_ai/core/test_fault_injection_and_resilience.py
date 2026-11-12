"""Tests for Fault Injection, Resilience, and Soak Testing (Workstream 18)."""
from __future__ import annotations

from pathlib import Path
import time

import pytest

from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.runtime import EntityRuntime, EntityRuntimeMode
from jaeger_ai.core.tasks import DurableTask, SqliteDurableTaskStore








def test_durable_background_task_recovery(tmp_path: Path):
    db_path = tmp_path / "durable_tasks.sqlite3"
    store = SqliteDurableTaskStore(db_path)

    # 1. Enqueue task before simulated restart
    task = DurableTask('compaction', 'test_agent', "Perform database compaction in background")
    store.admit_task(task)
    assert task.state.value == "queued"


    # 2. Simulate process crash / host restart
    del store

    # 3. Re-initialize store and recover
    new_store = SqliteDurableTaskStore(db_path)

    recovered = new_store.get_task(task.task_id)
    assert recovered is not None
    assert recovered.task_id == task.task_id
    assert recovered.goal == "Perform database compaction in background"
    assert recovered.state.value == "queued"




