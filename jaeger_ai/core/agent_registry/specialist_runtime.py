"""Native specialist runtime — real child execution, not a registration stub.

Lead identity and the dispatcher conversation stay with the parent. The
specialist runs on an isolated native session using existing MCP/delegate
contracts. Relationship knowledge is never treated as a tool permission.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from jaeger_agent.delegates.contracts import (
    DelegateEvent,
    DelegateHandle,
    DelegateRequest,
    DelegateResult,
    RuntimeStatus,
)

MAX_DELEGATION_DEPTH = 2
MAX_FANOUT = 3
DEFAULT_TIMEOUT_S = 120


def specialist_session(agent_id: str, request_id: str) -> str:
    """Isolated native session. Never the shared dispatcher conversation."""
    safe_agent = "".join(ch if ch.isalnum() or ch in "._-:" else "_" for ch in agent_id)[:80]
    return f"specialist:{safe_agent}:{request_id[:32]}"


def bounded_prompt(
    *,
    display_name: str,
    specialty: str,
    task: str,
    permitted_context: str = "",
    allowed_tools: frozenset[str] | None = None,
) -> str:
    tools = ", ".join(sorted(allowed_tools)) if allowed_tools else "none"
    context = (permitted_context or "").strip() or "(no additional context granted)"
    return (
        f"You are {display_name}, the {specialty} specialist for a bounded child task.\n"
        "You are not the lead. Do not take over the lead conversation or identity.\n"
        "Relationship membership is not permission to execute tools.\n"
        f"Permitted tools: {tools}.\n"
        f"Permitted context:\n{context}\n"
        f"Task:\n{task.strip()}\n"
        "Return only the specialist result and the evidence you actually obtained. "
        "If you cannot complete the task, say so explicitly."
    )


def check_delegation_limits(
    *,
    from_agent_id: str,
    to_agent_id: str,
    parent_chain: list[str],
    depth: int,
    active_children: int,
) -> str | None:
    if not to_agent_id:
        return "target agent is required"
    if to_agent_id == from_agent_id:
        return "an agent cannot delegate to itself"
    if to_agent_id in parent_chain:
        return "recursive delegation loop rejected"
    if depth >= MAX_DELEGATION_DEPTH:
        return f"delegation depth {depth} exceeds maximum {MAX_DELEGATION_DEPTH}"
    if active_children >= MAX_FANOUT:
        return f"parent already has {active_children} active children; max {MAX_FANOUT}"
    return None


class NativeSpecialistRuntime:
    """DelegateRuntime that drives one isolated native MCP turn."""

    runtime_id = "jaeger_native_specialist"

    def __init__(self, chat) -> None:
        self._chat = chat
        self._results: dict[str, DelegateResult] = {}
        self._events: dict[str, list[DelegateEvent]] = {}
        self._cancelled: set[str] = set()

    async def probe(self) -> RuntimeStatus:
        return RuntimeStatus(
            True,
            "native transport configured; actual availability is checked at execution",
            frozenset({"chat"}),
            False,  # The native host may use a cloud model; no local-only claim.
        )

    async def start(self, request: DelegateRequest) -> DelegateHandle:
        session = specialist_session(
            str(request.metadata.get("to_agent_id") or "specialist"),
            request.idempotency_key or request.task_id,
        )
        self._events[request.task_id] = [
            DelegateEvent(1, "started", {"session": session, "parent": request.parent_task_id})
        ]
        handle = DelegateHandle(request.task_id, self.runtime_id, session)
        timeout = min(int(request.timeout_seconds), 600)
        try:
            if request.task_id in self._cancelled:
                raise asyncio.CancelledError()
            text, backend = await asyncio.wait_for(self._chat(
                session, request.prompt, request_id=request.idempotency_key,
                allowed_tools=sorted(request.allowed_tools),
            ), timeout=timeout)
            if request.task_id in self._cancelled:
                self._results[request.task_id] = DelegateResult(
                    "cancelled",
                    "Specialist cancellation requested before a confirmed result",
                    evidence=({"backend": backend, "session": session},),
                    worker_session_id=session,
                )
            elif not text:
                self._results[request.task_id] = DelegateResult(
                    "failed",
                    "Specialist returned no confirmed result",
                    evidence=({"backend": backend, "session": session},),
                    worker_session_id=session,
                    metadata={"execution_unknown": True},
                )
            else:
                self._results[request.task_id] = DelegateResult(
                    "completed",
                    text,
                    evidence=({"backend": backend, "session": session, "output": text},),
                    worker_session_id=session,
                    metadata={"backend": backend},
                )
        except asyncio.CancelledError:
            self._results[request.task_id] = DelegateResult(
                "failed", "Specialist wait cancelled; native outcome is unconfirmed",
                worker_session_id=session, metadata={"execution_unknown": True}
            )
        except TimeoutError:
            self._results[request.task_id] = DelegateResult(
                "failed",
                "Specialist timed out; outcome is unconfirmed",
                worker_session_id=session,
                metadata={"execution_unknown": True, "timeout": True},
            )
        except Exception as exc:  # noqa: BLE001 — parent must observe the failure
            self._results[request.task_id] = DelegateResult(
                "failed",
                f"Specialist execution failed: {type(exc).__name__}: {exc}",
                worker_session_id=session,
                metadata={"error_type": type(exc).__name__, "execution_unknown": True},
            )
        self._events[request.task_id].append(
            DelegateEvent(2, "finished", {"status": self._results[request.task_id].status})
        )
        return handle

    def stream(self, handle: DelegateHandle) -> AsyncIterator[DelegateEvent]:
        async def _gen() -> AsyncIterator[DelegateEvent]:
            for event in self._events.get(handle.task_id, ()):
                yield event
        return _gen()

    async def result(self, handle: DelegateHandle) -> DelegateResult:
        result = self._results.get(handle.task_id)
        if result is None:
            return DelegateResult("failed", "Specialist result was never produced")
        return result

    async def cancel(self, handle: DelegateHandle) -> None:
        self._cancelled.add(handle.task_id)

    async def resume(self, handle: DelegateHandle, message: str) -> DelegateHandle:
        raise RuntimeError("Specialist child runs are not automatically resumed")
