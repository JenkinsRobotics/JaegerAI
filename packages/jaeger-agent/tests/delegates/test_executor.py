from __future__ import annotations

import asyncio

import pytest

from jaeger_agent.cognition.runs import InMemoryRunStore
from jaeger_agent.delegates import (
    DelegateEvent,
    DelegateExecutor,
    DelegateHandle,
    DelegateRegistry,
    DelegateRequest,
    DelegateResult,
    RuntimeStatus,
)


class FakeRuntime:
    runtime_id = "fake"

    async def probe(self) -> RuntimeStatus:
        return RuntimeStatus(True, capabilities=frozenset({"code"}), local=True)

    async def start(self, request: DelegateRequest) -> DelegateHandle:
        return DelegateHandle(request.task_id, self.runtime_id, "worker-session")

    async def stream(self, handle: DelegateHandle):
        yield DelegateEvent(1, "progress", {"percent": 50})
        yield DelegateEvent(2, "artifact", {"path": "result.txt"})

    async def result(self, handle: DelegateHandle) -> DelegateResult:
        return DelegateResult(
            "completed",
            "done",
            worker_session_id=handle.worker_session_id,
            memory_candidates=({"content": "untrusted worker claim"},),
        )

    async def cancel(self, handle: DelegateHandle) -> None:
        return None

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle:
        return handle


def _request(task_id: str, *, sensitivity: str = "personal") -> DelegateRequest:
    return DelegateRequest(
        task_id=task_id,
        prompt="inspect the repository",
        required_capabilities=frozenset({"code"}),
        sensitivity=sensitivity,  # type: ignore[arg-type]
        idempotency_key=f"test:{task_id}",
    )


def test_executor_records_events_and_terminal_state_without_promoting_memory() -> None:
    registry = DelegateRegistry()
    registry.register(FakeRuntime())
    runs = InMemoryRunStore()
    run = runs.create("commitment", provider="fake")
    seen = []

    result = asyncio.run(
        DelegateExecutor(registry, runs).execute(
            "fake", _request(run.id), on_event=seen.append,
        )
    )

    assert result.status == "completed"
    assert result.memory_candidates == ({"content": "untrusted worker claim"},)
    assert runs.get(run.id).state == "completed"
    assert runs.latest_checkpoint(run.id).cursor["event_sequence"] == 2
    assert [event.sequence for event in seen] == [1, 2]


def test_request_rejects_relative_workspace() -> None:
    with pytest.raises(ValueError, match="absolute"):
        DelegateRequest(
            task_id="task",
            prompt="work",
            workspace=__import__("pathlib").Path("relative"),
            idempotency_key="key",
        )


def test_private_request_rejects_remote_runtime() -> None:
    class Remote(FakeRuntime):
        async def probe(self) -> RuntimeStatus:
            return RuntimeStatus(True, capabilities=frozenset({"code"}), local=False)

    registry = DelegateRegistry()
    registry.register(Remote())
    runs = InMemoryRunStore()
    run = runs.create("commitment", provider="fake")

    with pytest.raises(Exception, match="ineligible"):
        asyncio.run(DelegateExecutor(registry, runs).execute("fake", _request(run.id, sensitivity="private")))

    assert runs.get(run.id).state == "created"
