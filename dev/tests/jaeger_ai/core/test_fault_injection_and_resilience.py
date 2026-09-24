"""Tests for Fault Injection, Resilience, and Soak Testing (Workstream 18)."""
from __future__ import annotations

from pathlib import Path
import time

import pytest

from jaeger_ai.core.entity.identity import EntityIdentity
from jaeger_ai.core.entity.runtime import EntityRuntime, EntityRuntimeMode
from jaeger_ai.core.resilience import (
    FaultInjectionEngine,
    FaultOutcome,
    FaultScenario,
)
from jaeger_ai.core.tasks import DurableTask, SqliteDurableTaskStore


def test_provider_timeout_injection(tmp_path: Path):
    engine = FaultInjectionEngine(tmp_path / "resilience")
    engine.activate_fault(FaultScenario.PROVIDER_TIMEOUT)

    with pytest.raises(TimeoutError) as exc_info:
        engine.simulate_provider_call("Hello Jaeger", timeout_limit_s=0.01)

    assert "Provider timed out" in str(exc_info.value)
    engine.clear_faults()

    # After clearing fault, normal response returns
    res = engine.simulate_provider_call("Hello Jaeger")
    assert "Response to: Hello Jaeger" in res


def test_provider_500_failure_injection(tmp_path: Path):
    engine = FaultInjectionEngine(tmp_path / "resilience")
    engine.activate_fault(FaultScenario.PROVIDER_FAILURE)

    with pytest.raises(ConnectionError) as exc_info:
        engine.simulate_provider_call("Status check")

    assert "500 Internal Server Error" in str(exc_info.value)
    engine.clear_faults()


def test_effect_idempotency_mid_crash(tmp_path: Path):
    engine = FaultInjectionEngine(tmp_path / "resilience")
    engine.activate_fault(FaultScenario.KILL_MID_EFFECT)

    class MockEffectPipeline:
        def __init__(self):
            self.intents = {}

        def register_intent(self, request_id, run_id, proposal_id, intent_type, target):
            self.intents[(request_id, target)] = {
                "run_id": run_id,
                "proposal_id": proposal_id,
                "intent_type": intent_type,
            }
            return self.intents[(request_id, target)]

        def get_intent_by_target(self, request_id, target):
            return self.intents.get((request_id, target))

    pipeline = MockEffectPipeline()
    executed_count = 0

    def mock_executor():
        nonlocal executed_count
        executed_count += 1

    outcome = engine.test_effect_idempotency_mid_crash(
        effect_pipeline=pipeline,
        request_id="req_crash_1",
        run_id="run_crash_1",
        proposal_id="prop_crash_1",
        intent_type="file_write",
        target="/tmp/protected_file.txt",
        executor_fn=mock_executor,
    )

    assert outcome.injected is True
    assert outcome.duplicate_effects_prevented is True
    assert executed_count == 0  # Crash prevented execution
    assert outcome.recovered is True


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




def test_short_soak_multi_turn(tmp_path: Path):
    runtime = EntityRuntime(
        state_root=tmp_path / "soak_state",
        identity=EntityIdentity(
            entity_id="soak_agent",
            display_name="SoakAgent",
            created_at=time.time(),
            instance_name="soak_instance",
        ),
        mode=EntityRuntimeMode.TEST,
    )
    engine = FaultInjectionEngine(tmp_path / "resilience")

    soak_results = engine.run_soak_test(runtime, turn_count=5)
    assert soak_results["turns_executed"] == 5
    assert soak_results["errors"] == 0
    assert soak_results["leak_free"] is True
    assert soak_results["average_turn_ms"] > 0
