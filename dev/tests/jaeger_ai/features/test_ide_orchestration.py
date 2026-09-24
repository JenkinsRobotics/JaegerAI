"""Tests for Jaeger IDE Worker Orchestration feature."""

from __future__ import annotations

from pathlib import Path

import pytest

from jaeger_ai.features.ide_orchestration import (
    DeterministicFakeWorkerAdapter,
    DuplicateSubmissionConflict,
    IDEOrchestrationService,
    ParentTask,
    TaskBudget,
    VerificationResult,
    WorkerUnavailableError,
)
from jaeger_ai.features.ide_orchestration.contracts import TERMINAL_STATES


@pytest.mark.asyncio
async def test_read_only_worker_round_trip():
    """Prove one safe read-only worker round trip with deterministic adapter."""
    adapter = DeterministicFakeWorkerAdapter(
        worker_id="claude",
        outcome_state="completed",
        outcome_text="Audit completed: 0 defects found in read-only scope.",
        progress_steps=("Inspecting files", "Synthesizing report"),
    )
    service = IDEOrchestrationService({"claude": adapter})

    progress_events = []
    service.add_progress_hook(lambda p: progress_events.append(p))

    task = ParentTask(
        task_id="task_001",
        goal="Audit codebase dependencies in read-only mode",
        assigned_worker="claude",
        idempotency_key="idem_claude_audit_001",
        read_only=True,
        budget=TaskBudget(max_seconds=10.0, max_turns=1, max_cost_usd=0.0),
    )

    result = await service.execute_parent_task(task)

    assert result.task_id == "task_001"
    assert result.worker_id == "claude"
    assert result.state == "completed"
    assert "0 defects found" in result.output
    assert result.verification.verified is False
    assert result.budget_used_seconds >= 0.0

    states = [p.state for p in progress_events]
    assert "queued" in states
    assert "submitted" in states
    assert "running" in states


@pytest.mark.asyncio
async def test_idempotency_reconciliation_prevents_duplicate_submission():
    """Same-process duplicate submission reconciles without resending."""
    adapter = DeterministicFakeWorkerAdapter(
        worker_id="codex",
        outcome_state="completed",
        outcome_text="Refactored helper function.",
    )
    service = IDEOrchestrationService({"codex": adapter})

    task = ParentTask(
        task_id="task_002",
        goal="Refactor helper function",
        assigned_worker="codex",
        idempotency_key="idem_codex_002",
        budget=TaskBudget(max_seconds=5.0),
    )

    first_result = await service.execute_parent_task(task)
    assert len(adapter.submissions) == 1

    # Second submission with same idempotency key and task_id
    second_result = await service.execute_parent_task(task)
    assert len(adapter.submissions) == 1  # No second submission
    assert second_result.state == first_result.state
    assert second_result.output == first_result.output


@pytest.mark.asyncio
async def test_duplicate_submission_different_task_id_raises_conflict():
    """Verify that reusing an idempotency key with a new task ID raises conflict."""
    adapter = DeterministicFakeWorkerAdapter(worker_id="gemini")
    service = IDEOrchestrationService({"gemini": adapter})

    task1 = ParentTask(
        task_id="task_003a",
        goal="First goal",
        assigned_worker="gemini",
        idempotency_key="shared_idem_key",
    )
    await service.execute_parent_task(task1)

    task2 = ParentTask(
        task_id="task_003b",
        goal="Second conflicting goal",
        assigned_worker="gemini",
        idempotency_key="shared_idem_key",
    )
    with pytest.raises(DuplicateSubmissionConflict):
        await service.execute_parent_task(task2)


@pytest.mark.asyncio
async def test_cancellation_flow():
    """Verify cancellation aborts execution cleanly."""
    adapter = DeterministicFakeWorkerAdapter(
        worker_id="claude",
        delay_seconds=0.1,
        progress_steps=("Step 1", "Step 2", "Step 3"),
    )
    service = IDEOrchestrationService({"claude": adapter})

    task = ParentTask(
        task_id="task_004",
        goal="Long running task to cancel",
        assigned_worker="claude",
        idempotency_key="idem_cancel_004",
    )

    # Cancel immediately during first progress event
    def on_progress(p):
        if p.state == "running":
            import asyncio

            asyncio.create_task(service.cancel_task("task_004"))

    service.add_progress_hook(on_progress)
    result = await service.execute_parent_task(task)

    assert result.state == "failed"
    assert "cancelled" in result.output.lower() or result.evidence.get("cancelled")


@pytest.mark.asyncio
async def test_independent_verifier_rejects_hallucinated_success():
    """Verify independent check rejects bogus worker self-assertion."""
    adapter = DeterministicFakeWorkerAdapter(
        worker_id="gemini",
        outcome_state="completed",
        outcome_text="All done and verified by Gemini!",
    )
    service = IDEOrchestrationService({"gemini": adapter})

    task = ParentTask(
        task_id="task_005",
        goal="Critical check needing independent verification",
        assigned_worker="gemini",
        idempotency_key="idem_verify_005",
    )

    def strict_verifier(output: str, evidence: dict) -> VerificationResult:
        # Independent checker expects evidence digest
        if "expected_digest" not in evidence:
            return VerificationResult(
                verified=False,
                reason="Independent check failed: missing required digest in evidence",
            )
        return VerificationResult(verified=True, reason="Digest matched")

    result = await service.execute_parent_task(task, verifier=strict_verifier)

    assert result.state == "completed"
    assert result.verification.verified is False
    assert "missing required digest" in result.verification.reason


@pytest.mark.asyncio
async def test_worker_explicit_failure_states():
    """Verify explicit error states (quota, auth, blocked, unknown) are preserved."""
    for failure_state in ("quota", "auth", "blocked", "unknown"):
        adapter = DeterministicFakeWorkerAdapter(
            worker_id="codex",
            outcome_state=failure_state,  # type: ignore
            outcome_text=f"Worker halted with {failure_state}",
        )
        service = IDEOrchestrationService({"codex": adapter})

        task = ParentTask(
            task_id=f"task_{failure_state}",
            goal=f"Test {failure_state}",
            assigned_worker="codex",
            idempotency_key=f"idem_{failure_state}",
        )

        result = await service.execute_parent_task(task)
        assert result.state == failure_state
        assert failure_state in result.output


@pytest.mark.asyncio
async def test_unregistered_worker_fails_fast():
    """Verify selecting an unregistered worker raises WorkerUnavailableError."""
    service = IDEOrchestrationService({})
    task = ParentTask(
        task_id="task_unreg",
        goal="Run on missing worker",
        assigned_worker="nonexistent_worker",
        idempotency_key="idem_unreg",
    )
    with pytest.raises(WorkerUnavailableError):
        await service.execute_parent_task(task)


@pytest.mark.asyncio
async def test_list_workers_and_get_task():
    """Verify probes and current process-local task state."""
    adapter = DeterministicFakeWorkerAdapter(
        worker_id="claude",
        outcome_state="completed",
        outcome_text="Worker done.",
    )
    service = IDEOrchestrationService({"claude": adapter})

    workers = await service.list_workers()
    assert len(workers) == 1
    assert workers[0]["worker_id"] == "claude"
    assert workers[0]["available"] is True

    task = ParentTask(
        task_id="task_durable_01",
        goal="Check state preservation",
        assigned_worker="claude",
        idempotency_key="idem_durable_01",
    )
    await service.execute_parent_task(task)

    durable = service.get_task("task_durable_01")
    assert durable is not None
    assert durable["task_id"] == "task_durable_01"
    assert durable["state"] == "completed"
    assert len(durable["progress"]) > 0
    assert durable["result"]["output"] == "Worker done."


@pytest.mark.asyncio
async def test_delegate_runtime_adapter_flow():
    """Verify DelegateRuntimeAdapter converts DelegateRuntime protocol accurately."""
    from jaeger_agent.delegates.contracts import (
        DelegateArtifact,
        DelegateEvent,
        DelegateHandle,
        DelegateResult,
        RuntimeStatus,
    )

    from jaeger_ai.features.ide_orchestration.adapters import DelegateRuntimeAdapter

    class MockDelegateRuntime:
        runtime_id = "mock_delegate"

        async def probe(self):
            return RuntimeStatus(
                available=True, detail="mock 1.0", capabilities=frozenset({"code"})
            )

        async def start(self, request):
            return DelegateHandle(task_id=request.task_id, runtime_id=self.runtime_id)

        async def stream(self, handle):
            yield DelegateEvent(
                sequence=1, event_type="turn.progress", payload={"text": "Step 1"}
            )
            yield DelegateEvent(
                sequence=2, event_type="turn.progress", payload={"text": "Step 2"}
            )

        async def result(self, handle):
            return DelegateResult(
                status="completed",
                summary="Mock finished successfully",
                artifacts=(DelegateArtifact(kind="file", uri="file:///tmp/res.txt"),),
            )

        async def cancel(self, handle):
            pass

    adapter = DelegateRuntimeAdapter(MockDelegateRuntime())
    service = IDEOrchestrationService({"mock_delegate": adapter})

    task = ParentTask(
        task_id="task_mock_01",
        goal="Test delegate adapter",
        assigned_worker="mock_delegate",
        idempotency_key="idem_mock_01",
        read_only=False,
    )
    result = await service.execute_parent_task(task)
    assert result.state == "completed"
    assert "Mock finished successfully" in result.output
    assert result.verification.verified is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_gateway_orchestration_endpoints(tmp_path):
    """Verify Gateway exposes orchestration endpoints cleanly with isolated state."""
    from aiohttp.test_utils import TestClient, TestServer

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    adapter = DeterministicFakeWorkerAdapter(
        worker_id="claude",
        outcome_state="completed",
        outcome_text="Gateway integration passed.",
    )
    service = IDEOrchestrationService({"claude": adapter})

    store = GatewaySessionStore(tmp_path / "gw_orch.sqlite3")
    gateway_app = JaegerGatewayApp(store=store, orchestration=service)

    client = TestClient(TestServer(gateway_app.app))
    await client.start_server()
    try:
        # 1. GET /v1/orchestration/workers
        resp = await client.get("/v1/orchestration/workers")
        assert resp.status == 200
        data = await resp.json()
        assert len(data["workers"]) == 1
        assert data["workers"][0]["worker_id"] == "claude"

        # 2. POST /v1/orchestration/tasks
        resp = await client.post(
            "/v1/orchestration/tasks",
            json={
                "task_id": "gw_task_01",
                "goal": "Verify gateway route",
                "worker": "claude",
                "idempotency_key": "idem_gw_01",
                "read_only": True,
            },
        )
        assert resp.status in (200, 201)
        data = await resp.json()
        assert data["task_id"] == "gw_task_01"

        # Wait briefly for execution to complete
        import asyncio

        for _ in range(20):
            resp = await client.get("/v1/orchestration/tasks/gw_task_01")
            assert resp.status == 200
            data = await resp.json()
            if data["state"] == "completed":
                break
            await asyncio.sleep(0.05)

        assert data["state"] == "completed"
        assert data["result"]["output"] == "Gateway integration passed."

        # 3. GET /v1/orchestration/tasks/nonexistent -> 404
        resp = await client.get("/v1/orchestration/tasks/nonexistent")
        assert resp.status == 404

        # 4. POST /v1/orchestration/tasks/{id}/cancel on active in-flight task
        adapter_slow = DeterministicFakeWorkerAdapter(
            worker_id="slow_worker",
            delay_seconds=0.1,
            progress_steps=("Step 1", "Step 2", "Step 3"),
        )
        service.register_adapter(adapter_slow)
        resp = await client.post(
            "/v1/orchestration/tasks",
            json={
                "task_id": "gw_task_slow",
                "goal": "Slow task to cancel",
                "worker": "slow_worker",
                "idempotency_key": "idem_gw_slow",
            },
        )
        assert resp.status in (200, 201)
        resp = await client.post("/v1/orchestration/tasks/gw_task_slow/cancel")
        assert resp.status == 200
        cancel_data = await resp.json()
        assert cancel_data["cancelled"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_verification_checks_actual_file_and_completion_stays_separate(tmp_path):
    artifact = tmp_path / "answer.txt"
    artifact.write_text("expected")
    adapter = DeterministicFakeWorkerAdapter()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("file-check", "Check file", adapter.worker_id, "file-check")

    def verify(_output, _evidence):
        return VerificationResult(
            artifact.read_text() == "expected",
            "Compared disk content",
            (str(artifact),),
        )

    result = await service.execute_parent_task(task, verifier=verify)
    assert result.verification.verified
    assert result.verification.checked_artifacts == (str(artifact),)
    before = service.get_task(task.task_id).copy()
    assert await service.cancel_task(task.task_id) is False
    assert service.get_task(task.task_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"goal": "Changed"},
        {"assigned_worker": "other"},
        {"workspace": Path("/tmp/other")},
        {"read_only": False},
        {"budget": TaskBudget(max_seconds=1)},
        {"metadata": {"conversation": "changed"}},
        {"required_capabilities": frozenset({"existing_conversation"})},
        {"idempotency_key": "other-key"},
    ],
)
async def test_changed_admission_snapshot_conflicts(change):
    from dataclasses import replace

    adapter = DeterministicFakeWorkerAdapter()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("snapshot", "Original", adapter.worker_id, "snapshot")
    await service.execute_parent_task(task)
    with pytest.raises(DuplicateSubmissionConflict):
        await service.execute_parent_task(replace(task, **change))
    assert len(adapter.submissions) == 1


@pytest.mark.asyncio
async def test_concurrent_retry_joins_slow_probe_and_freezes_metadata():
    import asyncio
    from dataclasses import replace

    entered, release = asyncio.Event(), asyncio.Event()

    class SlowProbe(DeterministicFakeWorkerAdapter):
        async def probe(self):
            entered.set()
            await release.wait()
            return await super().probe()

    adapter = SlowProbe()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask(
        "concurrent",
        "Original",
        adapter.worker_id,
        "concurrent",
        metadata={"target": {"conversation": "original"}},
    )
    first = asyncio.create_task(service.execute_parent_task(task))
    await entered.wait()
    second = asyncio.create_task(service.execute_parent_task(task))
    await asyncio.sleep(0)
    with pytest.raises(DuplicateSubmissionConflict):
        await service.execute_parent_task(replace(task, goal="Conflicting"))
    task.metadata["target"]["conversation"] = "mutated"
    release.set()
    one, two = await asyncio.gather(first, second)
    assert one == two
    assert len(adapter.submissions) == 1
    assert adapter.submissions[0][0].metadata["target"]["conversation"] == "original"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["probe", "observe", "result", "submit"])
async def test_silent_worker_deadline_covers_every_await(phase):
    import asyncio

    class Silent(DeterministicFakeWorkerAdapter):
        async def probe(self):
            if phase == "probe":
                await asyncio.Event().wait()
            return await super().probe()

        async def submit(self, task):
            if phase == "submit":
                await asyncio.Event().wait()
            return await super().submit(task)

        async def observe(self, task_id, handle):
            if phase == "observe":
                await asyncio.Event().wait()
            async for progress in super().observe(task_id, handle):
                yield progress

        async def get_raw_result(self, handle):
            if phase == "result":
                await asyncio.Event().wait()
            return await super().get_raw_result(handle)

    adapter = Silent()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask(
        "timeout",
        "Wait",
        adapter.worker_id,
        "timeout",
        budget=TaskBudget(max_seconds=0.02),
    )
    result = await asyncio.wait_for(service.execute_parent_task(task), timeout=1)
    assert result.state == ("unknown" if phase == "submit" else "blocked")
    assert result.evidence["timed_out"]
    if phase in {"observe", "result"}:
        assert adapter.cancelled_handles
        assert result.evidence["worker_cancel_confirmed"]
    assert (await service.execute_parent_task(task)) == result


@pytest.mark.asyncio
async def test_cancel_during_probe_prevents_submission():
    import asyncio

    entered = asyncio.Event()

    class Waiting(DeterministicFakeWorkerAdapter):
        async def probe(self):
            entered.set()
            await asyncio.Event().wait()

    adapter = Waiting()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("cancel-probe", "Wait", adapter.worker_id, "cancel-probe")
    future = asyncio.create_task(service.execute_parent_task(task))
    await entered.wait()
    assert await service.cancel_task(task.task_id)
    result = await asyncio.wait_for(future, timeout=1)
    assert result.evidence["cancelled"]
    assert not adapter.submissions
    assert not await service.cancel_task(task.task_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["auth", "quota", "offline"])
async def test_unavailable_worker_leaves_honest_record(reason):
    class Unavailable(DeterministicFakeWorkerAdapter):
        async def probe(self):
            return {"available": False, "state": reason, "detail": reason}

    adapter = Unavailable()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("unavailable", "Wait", adapter.worker_id, "unavailable")
    result = await service.execute_parent_task(task)
    assert result.state == ("blocked" if reason == "offline" else reason)
    assert service.get_task(task.task_id)["result"]["output"] == reason
    assert not adapter.submissions


@pytest.mark.asyncio
async def test_cli_cannot_claim_existing_panel_or_read_only():
    from dataclasses import replace

    from jaeger_agent.delegates.contracts import RuntimeStatus

    from jaeger_ai.features.ide_orchestration.adapters import DelegateRuntimeAdapter

    class Runtime:
        runtime_id = "cli"
        starts = 0

        async def probe(self):
            return RuntimeStatus(
                True,
                capabilities=frozenset(
                    {
                        "code",
                        "existing_conversation",
                        "follow_up",
                        "read_only_enforced",
                    }
                ),
            )

        async def start(self, request):
            self.starts += 1
            raise AssertionError("Must not start for unsupported capability")

    runtime = Runtime()
    adapter = DelegateRuntimeAdapter(runtime)
    probe = await adapter.probe()
    assert probe["transport"] == "cli"
    assert probe["capabilities"] == ["code"]
    task = ParentTask("readonly", "Read", "cli", "readonly")
    service = IDEOrchestrationService({"cli": adapter})
    assert (await service.execute_parent_task(task)).state == "blocked"
    with pytest.raises(ValueError, match="read_only"):
        await adapter.submit(task)
    with pytest.raises(ValueError, match="required capabilities"):
        await adapter.submit(
            replace(
                task,
                read_only=False,
                required_capabilities=frozenset({"existing_conversation"}),
            )
        )
    assert runtime.starts == 0


@pytest.mark.asyncio
async def test_cancel_without_worker_acknowledgment_is_not_confirmed():
    import asyncio

    entered = asyncio.Event()

    class Unconfirmed(DeterministicFakeWorkerAdapter):
        async def observe(self, task_id, handle):
            entered.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover — keep this an async iterator

        async def cancel(self, handle):
            return False

    adapter = Unconfirmed()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("unconfirmed", "Wait", adapter.worker_id, "unconfirmed")
    future = asyncio.create_task(service.execute_parent_task(task))
    await entered.wait()
    assert await service.cancel_task(task.task_id)
    result = await asyncio.wait_for(future, timeout=1)
    assert result.evidence["cancelled"]
    assert result.evidence["worker_cancel_confirmed"] is False
    assert not result.verification.verified
    assert (await service.execute_parent_task(task)) == result
    assert len(adapter.submissions) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_admission_snapshots_concurrency_and_failure_records(tmp_path):
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    release = asyncio.Event()

    class SlowProbe(DeterministicFakeWorkerAdapter):
        async def probe(self):
            await release.wait()
            return await super().probe()

    worker = SlowProbe()
    service = IDEOrchestrationService({worker.worker_id: worker})
    gateway = JaegerGatewayApp(
        store=GatewaySessionStore(tmp_path / "gateway.sqlite3"), orchestration=service
    )
    client = TestClient(TestServer(gateway.app))
    await client.start_server()
    endpoint = "/v1/orchestration/tasks"

    async def terminal(task_id):
        async with asyncio.timeout(2):
            while True:
                response = await client.get(f"{endpoint}/{task_id}")
                assert response.status == 200
                record = await response.json()
                if record["result"] is not None:
                    return record
                await asyncio.sleep(0.01)

    body = {
        "task_id": "http-task",
        "goal": "Read fixture",
        "worker": worker.worker_id,
        "idempotency_key": "http-key",
        "workspace": str(tmp_path),
        "read_only": True,
        "budget": {"max_seconds": 5, "max_turns": 2, "max_cost_usd": 0},
        "metadata": {"target": {"conversation": "fixture-conversation"}},
        "required_capabilities": ["read_only_enforced"],
    }
    ordinary_request = asyncio.get_running_loop().create_future()
    gateway._running_tasks["orchestration:http-task"] = ordinary_request
    try:
        responses = await asyncio.gather(
            *(client.post(endpoint, json=body) for _ in range(4))
        )
        assert sorted(response.status for response in responses) == [200, 200, 200, 201]
        for response in responses:
            assert (await response.json())["task_id"] == "http-task"
        assert ("orchestration", "http-task") in gateway._running_tasks
        assert gateway._running_tasks["orchestration:http-task"] is ordinary_request

        changes = [
            {"goal": "Different"},
            {"worker": "other-worker"},
            {"workspace": str(tmp_path / "other")},
            {"budget": {"max_seconds": 3}},
            {"metadata": {"target": "other"}},
            {"required_capabilities": ["existing_conversation"]},
            {"idempotency_key": "other-key"},
            {"task_id": "other-task"},
        ]
        for change in changes:
            response = await client.post(endpoint, json={**body, **change})
            assert response.status == 409, (change, await response.text())

        release.set()
        record = await terminal("http-task")
        assert record["state"] == "completed"
        assert record["result"]["verified"] is False
        assert len(worker.submissions) == 1
        accepted = worker.submissions[0][0]
        assert accepted.workspace == tmp_path
        assert accepted.required_capabilities == frozenset({"read_only_enforced"})
        assert accepted.metadata == body["metadata"]
        assert accepted.budget.max_turns == 2
        await asyncio.sleep(0)
        assert ("orchestration", "http-task") not in gateway._running_tasks
        assert gateway._running_tasks.pop("orchestration:http-task") is ordinary_request
        ordinary_request.cancel()
        replay = await client.post(endpoint, json=body)
        assert replay.status == 200
        assert (await replay.json())["result"] == record["result"]
        cancel = await client.post(f"{endpoint}/http-task/cancel", json={})
        assert (await cancel.json())["cancelled"] is False

        missing = {
            **body,
            "task_id": "missing",
            "idempotency_key": "missing",
            "worker": "absent",
        }
        response = await client.post(endpoint, json=missing)
        assert response.status == 404
        assert "not registered" in (await response.json())["error"]
        assert ("orchestration", "missing") not in gateway._running_tasks

        unsupported = {
            **body,
            "task_id": "unsupported",
            "idempotency_key": "unsupported",
            "required_capabilities": ["existing_conversation"],
        }
        assert (await client.post(endpoint, json=unsupported)).status == 201
        blocked = await terminal("unsupported")
        assert blocked["state"] == "blocked"
        assert "existing_conversation" in blocked["result"]["output"]
        assert len(worker.submissions) == 1

        for invalid in [
            [],
            {**body, "read_only": "false"},
            {**body, "budget": []},
            {**body, "budget": {"max_seconds": -1}},
            {**body, "budget": {"max_turns": 1.5}},
            {**body, "metadata": []},
            {**body, "workspace": "relative"},
            {**body, "required_capabilities": "existing_conversation"},
        ]:
            response = await client.post(endpoint, json=invalid)
            assert response.status == 400, await response.text()
        assert not gateway._running_tasks
    finally:
        release.set()
        ordinary_request.cancel()
        await client.close()


@pytest.mark.asyncio
async def test_owner_cancellation_before_worker_starts_is_recorded_and_replayed():
    import asyncio

    adapter = DeterministicFakeWorkerAdapter()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("early-cancel", "Wait", adapter.worker_id, "early-cancel")
    operation, replayed = service.admit_parent_task(task)
    assert replayed is False
    operation.cancel()
    await asyncio.gather(operation, return_exceptions=True)
    await asyncio.sleep(0)
    record = service.get_task(task.task_id)
    assert record["state"] == "failed"
    assert record["result"]["evidence"] == {"cancelled": True, "submitted": False}
    result = await service.execute_parent_task(task)
    assert result.evidence["submitted"] is False
    assert not adapter.submissions


def test_unknown_is_a_terminal_orchestration_state():
    assert "unknown" in TERMINAL_STATES


@pytest.mark.asyncio
async def test_cancel_all_confirms_adapter_cancel_before_returning():
    import asyncio

    entered = asyncio.Event()
    events: list[str] = []

    class Waiting(DeterministicFakeWorkerAdapter):
        async def observe(self, task_id, handle):
            entered.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover - keep this an async iterator

        async def cancel(self, handle):
            events.append("adapter_cancel")
            return await super().cancel(handle)

    adapter = Waiting()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    task = ParentTask("shutdown", "Wait", adapter.worker_id, "shutdown")
    operation, _ = service.admit_parent_task(task)
    await entered.wait()

    assert await service.cancel_all() == ()
    result = await operation
    assert events == ["adapter_cancel"]
    assert result.evidence["worker_cancel_confirmed"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_gateway_shutdown_cancels_worker_before_store_release(tmp_path, monkeypatch):
    import asyncio

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    entered = asyncio.Event()
    events: list[str] = []

    class Waiting(DeterministicFakeWorkerAdapter):
        async def observe(self, task_id, handle):
            entered.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover - keep this an async iterator

        async def cancel(self, handle):
            events.append("adapter_cancel")
            return await super().cancel(handle)

    adapter = Waiting()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    store = GatewaySessionStore(tmp_path / "shutdown.sqlite3")
    gateway = JaegerGatewayApp(store=store, orchestration=service)
    gateway._owns_store = True
    monkeypatch.setattr(store, "recover_interrupted_sessions", lambda: None)
    monkeypatch.setattr(store, "release_process", lambda: events.append("release"))

    task = ParentTask("shutdown-http", "Wait", adapter.worker_id, "shutdown-http")
    operation, _ = service.admit_parent_task(task)
    gateway._running_tasks[("orchestration", task.task_id)] = operation
    await entered.wait()
    await gateway._bounded_shutdown(gateway.app)

    assert events == ["adapter_cancel", "release"]
    assert service.get_task(task.task_id)["result"]["evidence"]["worker_cancel_confirmed"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_http_rejects_writable_orchestration_before_submit(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    from jaeger_ai.core.gateway.server import JaegerGatewayApp
    from jaeger_ai.core.gateway.session_store import GatewaySessionStore

    adapter = DeterministicFakeWorkerAdapter()
    service = IDEOrchestrationService({adapter.worker_id: adapter})
    gateway = JaegerGatewayApp(
        store=GatewaySessionStore(tmp_path / "writable.sqlite3"), orchestration=service
    )
    client = TestClient(TestServer(gateway.app))
    await client.start_server()
    try:
        response = await client.post(
            "/v1/orchestration/tasks",
            json={
                "task_id": "write",
                "goal": "Change a file",
                "worker": adapter.worker_id,
                "workspace": str(tmp_path),
                "read_only": False,
            },
        )
        assert response.status == 403
        assert "server-owned authorization" in (await response.json())["error"]
        assert adapter.submissions == []
        assert service.get_task("write") is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_completed_worker_receipt_survives_owner_restart(tmp_path):
    adapter = DeterministicFakeWorkerAdapter(worker_id='codex', outcome_text='Completed work')
    first = IDEOrchestrationService({'codex':adapter})
    first.bind_store(tmp_path/'gateway.sqlite3')
    task = ParentTask(task_id='persisted', goal='Perform work', assigned_worker='codex', idempotency_key='persistent-key')
    original = await first.execute_parent_task(task)
    second = IDEOrchestrationService({'codex':adapter})
    second.bind_store(tmp_path/'gateway.sqlite3')
    replay = await second.execute_parent_task(task)
    assert replay.output == original.output
    assert len(adapter.submissions) == 1
    assert second.get_task(task.task_id)['progress'] == first.get_task(task.task_id)['progress']


@pytest.mark.asyncio
async def test_live_worker_recovery_after_owner_sigkill(tmp_path):
    import asyncio
    import os
    import subprocess
    import sys
    from jaeger_agent.delegates.process import CommandSpec, SubprocessDelegateRuntime
    from jaeger_ai.features.ide_orchestration.adapters import DelegateRuntimeAdapter
    program = "from pathlib import Path; import time; p=Path('effects.txt'); p.write_text(p.read_text()+'x' if p.exists() else 'x'); time.sleep(1); print('recovered actual result')"
    script = tmp_path/'owner.py'
    script.write_text('''import asyncio, sys
from pathlib import Path
from jaeger_agent.delegates.process import CommandSpec, SubprocessDelegateRuntime
from jaeger_ai.features.ide_orchestration import IDEOrchestrationService, ParentTask, TaskBudget
from jaeger_ai.features.ide_orchestration.adapters import DelegateRuntimeAdapter
root=Path(sys.argv[1])
program=sys.argv[2]
async def main():
    spec=CommandSpec('recover', (sys.executable,), lambda *a: ('-c',program), frozenset(), True)
    service=IDEOrchestrationService({'recover':DelegateRuntimeAdapter(SubprocessDelegateRuntime(spec))})
    service.bind_store(root/'gateway.sqlite3')
    task=ParentTask('live','Build report','recover','live-key',workspace=root,read_only=False,budget=TaskBudget(max_seconds=10))
    service.admit_parent_task(task)
    while not service.get_task('live').get('handle'):
        await asyncio.sleep(.01)
    (root/'owner-ready').touch()
    await asyncio.Event().wait()
asyncio.run(main())
''')
    child = subprocess.Popen([sys.executable, '-B', str(script), str(tmp_path), program],
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(500):
            if (tmp_path/'owner-ready').exists():
                break
            if child.poll() is not None:
                raise AssertionError(child.communicate()[1].decode())
            await asyncio.sleep(.01)
        assert (tmp_path/'owner-ready').exists()
        child.kill(); child.wait(timeout=5)
        spec = CommandSpec('recover', (sys.executable,), lambda *a: ('-c',program), frozenset(), True)
        adapter = DelegateRuntimeAdapter(SubprocessDelegateRuntime(spec))
        restored = IDEOrchestrationService({'recover':adapter})
        restored.bind_store(tmp_path/'gateway.sqlite3')
        restored.resume_pending()
        task = ParentTask('live','Build report','recover','live-key',workspace=tmp_path,read_only=False,budget=TaskBudget(max_seconds=10))
        result = await restored.execute_parent_task(task)
        assert result.state == 'completed'
        assert result.output == 'recovered actual result'
        assert (tmp_path/'effects.txt').read_text() == 'x'
    finally:
        if child.poll() is None:
            child.kill(); child.wait(timeout=5)
