"""External delegate lifecycle coordinated with Jaeger's durable run store."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from jaeger_agent.cognition.runs import RunStore

from .contracts import DelegateEvent, DelegateRequest, DelegateResult
from .health import DelegateHealthStore, DelegateObservation, get_delegate_health_store
from .registry import DelegateRegistry


class DelegateExecutionError(RuntimeError):
    pass


class AllDelegatesFailed(DelegateExecutionError):
    """Every candidate in a failover chain was tried and none completed.

    Carries the per-delegate causes so the caller can report *why* the chain
    ran out rather than just that it did — the difference between "nothing
    was installed" and "all four were installed and each rejected the work".
    """

    def __init__(self, attempts: "tuple[FailoverAttempt, ...]") -> None:
        self.attempts = attempts
        detail = ", ".join(f"{a.runtime_id}: {a.error}" for a in attempts) or "no candidates"
        super().__init__(f"all delegates failed ({detail})")


@dataclass(frozen=True, slots=True)
class FailoverAttempt:
    runtime_id: str
    error: str


@dataclass(frozen=True, slots=True)
class EnsembleOutcome:
    """One delegate's contribution to an ensemble — a result or a reason."""

    runtime_id: str
    result: DelegateResult | None
    error: str | None


class DelegateExecutor:
    """Run one registered delegate and mirror its lifecycle into a Jaeger run.

    The caller creates the run because it owns the surrounding commitment and
    lineage.  This class only performs legal transitions and checkpoints
    runtime events; it never writes delegate-proposed memories.
    """

    def __init__(
        self,
        registry: DelegateRegistry,
        runs: RunStore,
        health: DelegateHealthStore | None = None,
    ) -> None:
        self.registry = registry
        self.runs = runs
        self.health = health or get_delegate_health_store()

    async def execute(
        self,
        runtime_id: str,
        request: DelegateRequest,
        *,
        on_event: Callable[[DelegateEvent], None] | None = None,
    ) -> DelegateResult:
        runtime = self.registry.get(runtime_id)
        if runtime is None:
            raise DelegateExecutionError(f"unknown delegate runtime: {runtime_id}")
        status = await runtime.probe()
        require_local = request.sensitivity in {"private", "secret"}
        if not self.registry.eligible(
            status,
            required_capabilities=request.required_capabilities,
            require_local=require_local,
        ):
            raise DelegateExecutionError(
                f"delegate runtime {runtime_id!r} is unavailable or ineligible"
            )

        run = self.runs.get(request.task_id)
        if run is None:
            raise DelegateExecutionError(f"delegate run does not exist: {request.task_id}")
        if run.state == "created":
            self.runs.transition(run.id, "active")

        started = time.monotonic()
        try:
            handle = await runtime.start(request)
            async for event in runtime.stream(handle):
                self.runs.checkpoint(
                    run.id,
                    {
                        "runtime_id": runtime_id,
                        "worker_session_id": handle.worker_session_id,
                        "event_sequence": event.sequence,
                        "event_type": event.event_type,
                        "payload": event.payload,
                    },
                )
                if on_event is not None:
                    on_event(event)
            result = await runtime.result(handle)
        except BaseException as exc:
            self._record(request, runtime_id, False, started, error=type(exc).__name__)
            current = self.runs.get(run.id)
            if current is not None and current.state == "active":
                self.runs.transition(run.id, "blocked", reason=f"delegate_error:{type(exc).__name__}")
            raise

        terminal = {
            "completed": "completed",
            "blocked": "blocked",
            "failed": "failed",
            "cancelled": "cancelled",
        }[result.status]
        current = self.runs.get(run.id)
        if current is not None and current.state == "active":
            self.runs.transition(run.id, terminal, reason=f"delegate:{result.status}")
        self._record(
            request,
            runtime_id,
            result.status == "completed",
            started,
            quality=result.metadata.get("quality"),
            cost_usd=result.metadata.get("cost_usd"),
            error=None if result.status == "completed" else result.status,
        )
        return result

    async def execute_with_fallback(
        self,
        runtime_ids: Sequence[str],
        request: DelegateRequest,
        *,
        on_event: Callable[[DelegateEvent], None] | None = None,
        on_failover: Callable[[str, BaseException], None] | None = None,
    ) -> DelegateResult:
        """Try each delegate in order and return the first completed result.

        ``execute`` is the single-delegate path and stays exactly as it was:
        it raises, and the run goes to ``blocked``. This wrapper is for the
        case where the caller has alternatives — it swallows a failure only
        so it can try the next candidate, and re-raises as
        :class:`AllDelegatesFailed` once the list is exhausted.

        A delegate that returns a non-completed *result* (``failed``,
        ``blocked``) counts as a failure too: an agent CLI that exits 0 while
        refusing the work is the same outcome to the caller as one that
        crashed, and both should hand off. ``execute`` has already recorded
        health for either shape, so the ranking learns from the whole chain.

        The run is re-opened between attempts because ``execute`` transitions
        it to a terminal state on the way out; without that, attempt two would
        fail its own state check rather than the delegate's.
        """
        attempts: list[FailoverAttempt] = []
        for runtime_id in runtime_ids:
            run = self.runs.get(request.task_id)
            if run is not None and run.state in {"blocked", "failed"}:
                self.runs.transition(run.id, "active", reason="delegate_failover_retry")
            try:
                result = await self.execute(runtime_id, request, on_event=on_event)
            except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised below
                attempts.append(FailoverAttempt(runtime_id, type(exc).__name__))
                if on_failover is not None:
                    on_failover(runtime_id, exc)
                continue
            if result.status == "completed":
                return result
            # A refusal is a handoff too, so it has to reach on_failover the
            # same way a crash does — otherwise the chain silently skips a
            # delegate and the operator cannot tell it was ever tried.
            attempts.append(FailoverAttempt(runtime_id, f"status:{result.status}"))
            if on_failover is not None:
                on_failover(
                    runtime_id,
                    DelegateExecutionError(
                        f"{runtime_id} returned {result.status}: "
                        f"{(result.summary or '').strip()[:160]}"
                    ),
                )
        raise AllDelegatesFailed(tuple(attempts))

    async def execute_ensemble(
        self,
        runtime_ids: Sequence[str],
        request: DelegateRequest,
        *,
        require: int = 1,
    ) -> "tuple[EnsembleOutcome, ...]":
        """Run the same request on several delegates at once.

        Failover asks "who can do this?"; an ensemble asks "what do several
        of them say?" — useful when the answer matters more than the latency
        and disagreement between agents is itself signal.

        Every delegate gets its OWN run, because a run is the unit of
        lineage and two delegates sharing one would interleave their
        checkpoints into an unreadable history. Failures are returned rather
        than raised: a partial ensemble is still useful, and the caller
        decides whether ``require`` completions is enough.
        """
        async def one(runtime_id: str) -> EnsembleOutcome:
            run = self.runs.create("ensemble", provider=runtime_id)
            scoped = replace(request, task_id=run.id)
            try:
                result = await self.execute(runtime_id, scoped)
            except BaseException as exc:  # noqa: BLE001 — reported, not raised
                return EnsembleOutcome(runtime_id, None, type(exc).__name__)
            return EnsembleOutcome(runtime_id, result, None)

        outcomes = tuple(
            await asyncio.gather(*(one(rid) for rid in runtime_ids))
        )
        completed = [o for o in outcomes if o.result is not None
                     and o.result.status == "completed"]
        if len(completed) < require:
            raise AllDelegatesFailed(tuple(
                FailoverAttempt(o.runtime_id, o.error or f"status:{o.result.status}")
                for o in outcomes if o not in completed
            ))
        return outcomes

    def _record(
        self,
        request: DelegateRequest,
        runtime_id: str,
        success: bool,
        started: float,
        *,
        quality: object = None,
        cost_usd: object = None,
        error: str | None = None,
    ) -> None:
        capability = (
            min(request.required_capabilities)
            if request.required_capabilities
            else "general"
        )
        self.health.record(
            DelegateObservation(
                runtime_id=runtime_id,
                capability=capability,
                success=success,
                latency_ms=round((time.monotonic() - started) * 1000),
                quality=float(quality) if isinstance(quality, (int, float)) else None,
                cost_usd=float(cost_usd) if isinstance(cost_usd, (int, float)) else None,
                error_category=error,
                metadata={"task_id": request.task_id},
            )
        )
