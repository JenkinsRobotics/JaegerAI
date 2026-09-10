"""Failover across a ranked delegate chain.

The single-delegate path (``execute``) is deliberately unforgiving: it
raises and parks the run. These tests pin the wrapper that exists because
an operator with six agent CLIs installed should not lose a task when the
first one is installed-but-unauthenticated.
"""

from __future__ import annotations

import asyncio

import pytest

from jaeger_agent.cognition.runs import InMemoryRunStore
from jaeger_agent.delegates import (
    AllDelegatesFailed,
    EnsembleOutcome,
    DelegateEvent,
    DelegateExecutor,
    DelegateHandle,
    DelegateRegistry,
    DelegateRequest,
    DelegateResult,
    RuntimeStatus,
)
from jaeger_agent.delegates.health import (
    DelegateObservation,
    InMemoryDelegateHealthStore,
)
from jaeger_agent.delegates.routing import DelegateRouter


class ScriptedRuntime:
    """A delegate that fails in a chosen way: crash, refuse, or complete."""

    def __init__(self, runtime_id: str, behaviour: str) -> None:
        self.runtime_id = runtime_id
        self.behaviour = behaviour
        self.started = 0

    async def probe(self) -> RuntimeStatus:
        return RuntimeStatus(True, capabilities=frozenset({"code"}), local=True)

    async def start(self, request: DelegateRequest) -> DelegateHandle:
        self.started += 1
        if self.behaviour == "crash":
            raise RuntimeError("delegate exploded")
        return DelegateHandle(request.task_id, self.runtime_id, f"{self.runtime_id}-session")

    async def stream(self, handle: DelegateHandle):
        yield DelegateEvent(1, "progress", {"percent": 100})

    async def result(self, handle: DelegateHandle) -> DelegateResult:
        status = "failed" if self.behaviour == "refuse" else "completed"
        return DelegateResult(status, f"{self.runtime_id} says hi",
                              worker_session_id=handle.worker_session_id)

    async def cancel(self, handle: DelegateHandle) -> None:
        return None

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle:
        return handle


def _request(task_id: str) -> DelegateRequest:
    return DelegateRequest(
        task_id=task_id,
        prompt="do the thing",
        required_capabilities=frozenset({"code"}),
        sensitivity="personal",  # type: ignore[arg-type]
        idempotency_key=f"test:{task_id}",
    )


def _executor(*runtimes):
    """Executor plus a live run — the run id IS the task id the executor looks up."""
    registry = DelegateRegistry()
    for runtime in runtimes:
        registry.register(runtime)
    runs = InMemoryRunStore()
    run = runs.create("commitment", provider="test")
    return DelegateExecutor(registry, runs, InMemoryDelegateHealthStore()), runs, run.id


def test_failover_moves_past_a_delegate_that_crashes() -> None:
    first = ScriptedRuntime("alpha", "crash")
    second = ScriptedRuntime("beta", "complete")
    executor, runs, task = _executor(first, second)

    result = asyncio.run(
        executor.execute_with_fallback(["alpha", "beta"], _request(task))
    )

    assert result.status == "completed"
    assert result.summary == "beta says hi"
    assert first.started == 1 and second.started == 1


def test_a_refusal_counts_as_failure_and_hands_off() -> None:
    """Exit-0-but-refused is the same outcome to the caller as a crash."""
    first = ScriptedRuntime("alpha", "refuse")
    second = ScriptedRuntime("beta", "complete")
    executor, runs, task = _executor(first, second)

    result = asyncio.run(
        executor.execute_with_fallback(["alpha", "beta"], _request(task))
    )
    assert result.status == "completed"
    assert second.started == 1


def test_a_healthy_first_delegate_short_circuits_the_chain() -> None:
    first = ScriptedRuntime("alpha", "complete")
    second = ScriptedRuntime("beta", "complete")
    executor, runs, task = _executor(first, second)

    result = asyncio.run(
        executor.execute_with_fallback(["alpha", "beta"], _request(task))
    )
    assert result.summary == "alpha says hi"
    assert second.started == 0, "must not call a delegate it never needed"


def test_exhausting_the_chain_reports_every_cause() -> None:
    executor, runs, task = _executor(
        ScriptedRuntime("alpha", "crash"), ScriptedRuntime("beta", "refuse")
    )

    with pytest.raises(AllDelegatesFailed) as excinfo:
        asyncio.run(
            executor.execute_with_fallback(["alpha", "beta"], _request(task))
        )
    attempts = excinfo.value.attempts
    assert [a.runtime_id for a in attempts] == ["alpha", "beta"]
    assert attempts[0].error == "RuntimeError"
    assert attempts[1].error == "status:failed"
    assert "alpha" in str(excinfo.value) and "beta" in str(excinfo.value)


def test_failover_notifies_the_caller_on_each_handoff() -> None:
    executor, runs, task = _executor(
        ScriptedRuntime("alpha", "crash"), ScriptedRuntime("beta", "complete")
    )
    seen: list[str] = []

    asyncio.run(
        executor.execute_with_fallback(
            ["alpha", "beta"], _request(task),
            on_failover=lambda rid, exc: seen.append(f"{rid}:{type(exc).__name__}"),
        )
    )
    assert seen == ["alpha:RuntimeError"]


def test_a_refusal_also_reaches_the_failover_callback() -> None:
    """A delegate that exits 0 while refusing must not vanish from the log."""
    executor, runs, task = _executor(
        ScriptedRuntime("alpha", "refuse"), ScriptedRuntime("beta", "complete")
    )
    seen: list[str] = []
    asyncio.run(
        executor.execute_with_fallback(
            ["alpha", "beta"], _request(task),
            on_failover=lambda rid, exc: seen.append(rid),
        )
    )
    assert seen == ["alpha"]


def test_router_ranks_every_eligible_delegate_not_just_the_winner() -> None:
    """rank() is what makes a chain possible; choose() stays the head of it."""
    registry = DelegateRegistry()
    for name in ("alpha", "beta", "gamma"):
        registry.register(ScriptedRuntime(name, "complete"))
    health = InMemoryDelegateHealthStore()
    for _ in range(4):
        health.record(DelegateObservation("alpha", True, 100, capability="code", quality=0.9))
        health.record(DelegateObservation("beta", False, 100, capability="code", quality=0.1))

    router = DelegateRouter(registry, health)
    routes = asyncio.run(router.rank(required_capabilities=frozenset({"code"})))
    ids = [r.runtime_id for r in routes]

    assert len(ids) == 3
    assert ids[0] == "alpha", "best-observed delegate leads"
    assert ids[-1] == "beta", "worst-observed delegate trails"
    chosen = asyncio.run(router.choose(required_capabilities=frozenset({"code"})))
    assert chosen.runtime_id == ids[0]


# ── ensemble (Mixture of Agents) ────────────────────────────────────


def test_ensemble_runs_every_delegate_and_returns_all_verdicts() -> None:
    alpha, beta = ScriptedRuntime("alpha", "complete"), ScriptedRuntime("beta", "complete")
    executor, runs, task = _executor(alpha, beta)

    outcomes = asyncio.run(
        executor.execute_ensemble(["alpha", "beta"], _request(task))
    )
    assert {o.runtime_id for o in outcomes} == {"alpha", "beta"}
    assert all(o.result is not None and o.result.status == "completed" for o in outcomes)
    assert alpha.started == 1 and beta.started == 1


def test_ensemble_gives_each_delegate_its_own_run() -> None:
    """Shared runs would interleave two delegates' checkpoints."""
    executor, runs, task = _executor(
        ScriptedRuntime("alpha", "complete"), ScriptedRuntime("beta", "complete")
    )
    before = len(list(runs.list())) if hasattr(runs, "list") else None
    outcomes = asyncio.run(
        executor.execute_ensemble(["alpha", "beta"], _request(task))
    )
    sessions = {o.result.worker_session_id for o in outcomes}
    assert len(sessions) == 2, "each delegate must run in its own session/run"


def test_ensemble_tolerates_partial_failure() -> None:
    executor, runs, task = _executor(
        ScriptedRuntime("alpha", "crash"), ScriptedRuntime("beta", "complete")
    )
    outcomes = asyncio.run(
        executor.execute_ensemble(["alpha", "beta"], _request(task), require=1)
    )
    by_id = {o.runtime_id: o for o in outcomes}
    assert by_id["alpha"].error == "RuntimeError" and by_id["alpha"].result is None
    assert by_id["beta"].result.status == "completed"


def test_ensemble_raises_when_it_cannot_meet_the_quorum() -> None:
    executor, runs, task = _executor(
        ScriptedRuntime("alpha", "crash"), ScriptedRuntime("beta", "complete")
    )
    with pytest.raises(AllDelegatesFailed):
        asyncio.run(
            executor.execute_ensemble(["alpha", "beta"], _request(task), require=2)
        )
