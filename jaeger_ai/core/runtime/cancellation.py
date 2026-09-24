"""Request-scoped cancellation (historical R03 task).

One :class:`CancellationScope` per admitted request. The Gateway registers it
at admission — before any worker can execute — and the execution owner binds
each agent that runs on the request's behalf. Cancelling the scope:

* sets a signal the agent loop treats as externally owned (the loop's own
  per-turn reset never clears it, so a cancel that lands before the agent
  starts is not lost), and
* interrupts every bound agent immediately, which the provider adapters
  observe through ``interruptible_call`` / their streaming loops.

It is deliberately *not* a global "stop everything" flag: another request's
scope, and the shared provider workers, are untouched. Terminal truth is not
decided here — the caller consults the run's effect ledger after the worker
returns (a completed effect stays recorded; a pending one stays unknown).
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class Interruptible(Protocol):
    def interrupt(self) -> None: ...


class CancellationScope:
    """Cancellation state for one request. Thread-safe; idempotent."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._agents: list[Interruptible] = []

    @property
    def cancelled(self) -> bool:
        return self.event.is_set()

    def cancel(self) -> bool:
        """Signal cancellation. Returns True only for the first call."""
        with self._lock:
            if self.event.is_set():
                return False
            self.event.set()
            agents = list(self._agents)
        for agent in agents:
            _interrupt(agent, self.request_id)
        return True

    def bind(self, agent: Interruptible) -> None:
        """Attach an agent executing this request. An agent bound after the
        cancel was requested is interrupted at once."""
        with self._lock:
            self._agents.append(agent)
            already = self.event.is_set()
        if already:
            _interrupt(agent, self.request_id)

    @property
    def interrupt_delivered(self) -> bool:
        """True when at least one live agent has been bound to this scope."""
        with self._lock:
            return bool(self._agents)


def _interrupt(agent: Interruptible, request_id: str) -> None:
    try:
        agent.interrupt()
    except Exception:  # noqa: BLE001 — one broken agent must not block the rest
        logger.warning("interrupt failed for request %s", request_id, exc_info=True)


class CancellationRegistry:
    """Scopes keyed by request id, owned by the Gateway control plane."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scopes: dict[str, CancellationScope] = {}

    def register(self, request_id: str) -> CancellationScope:
        with self._lock:
            scope = self._scopes.get(request_id)
            if scope is None:
                scope = self._scopes[request_id] = CancellationScope(request_id)
            return scope

    def get(self, request_id: str) -> CancellationScope | None:
        with self._lock:
            return self._scopes.get(request_id)

    def cancel(self, request_id: str) -> CancellationScope:
        """Cancel ``request_id``, registering it first if needed so a cancel
        that races admission bookkeeping is still honoured."""
        scope = self.register(request_id)
        scope.cancel()
        return scope

    def is_cancelled(self, request_id: str) -> bool:
        scope = self.get(request_id)
        return scope is not None and scope.cancelled

    def release(self, request_id: str) -> None:
        """Forget a scope once its worker has returned. Bound agents keep
        their own interrupt flag, so a detached worker still stops."""
        with self._lock:
            self._scopes.pop(request_id, None)


def bind_agent(scope: Any, agent: Any) -> None:
    """Bind ``agent`` to ``scope`` (a :class:`CancellationScope` or ``None``):
    the agent treats the scope's event as an externally owned cancel signal
    and is interrupted directly on cancel."""
    if scope is None:
        return
    binder = getattr(agent, "bind_cancel_signal", None)
    if callable(binder):
        binder(scope.event)
    scope.bind(agent)


__all__ = ["CancellationRegistry", "CancellationScope", "Interruptible", "bind_agent"]
