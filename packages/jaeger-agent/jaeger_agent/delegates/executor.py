"""External delegate lifecycle coordinated with Jaeger's durable run store."""

from __future__ import annotations

import time
from collections.abc import Callable

from jaeger_agent.cognition.runs import RunStore

from .contracts import DelegateEvent, DelegateRequest, DelegateResult
from .health import DelegateHealthStore, DelegateObservation, get_delegate_health_store
from .registry import DelegateRegistry


class DelegateExecutionError(RuntimeError):
    pass


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
