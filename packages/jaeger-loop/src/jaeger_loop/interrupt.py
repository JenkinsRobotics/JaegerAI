"""Interruptible call primitive, liveness beacon & isolated CancelScope tree."""

from __future__ import annotations

import threading
import time
from contextvars import copy_context
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class AgentInterrupted(Exception):
    """Raised when an interrupt event or CancelScope cancels an in-flight call."""


class StaleCallTimeout(Exception):
    """Raised when no progress was observed for ``stale_timeout`` seconds."""


class CancelScope:
    """Hierarchical cancellation scope isolating child sub-agents from killing their parent.

    - Cancelling a parent cascades immediately to all child scopes.
    - Cancelling a child leaves the parent and sibling scopes untouched.
    - Exposes ``.event`` (a ``threading.Event``) for direct use with ``interruptible_call``.
    """

    def __init__(self, *, parent: "CancelScope | None" = None, reason: str = "") -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._children: list[CancelScope] = []
        self._reason: str = reason
        if parent is not None:
            parent._attach(self)

    def _attach(self, child: "CancelScope") -> None:
        with self._lock:
            if self._event.is_set():
                child.cancel(self._reason or "parent cancelled")
            else:
                self._children.append(child)

    def child(self) -> "CancelScope":
        return CancelScope(parent=self)

    @property
    def event(self) -> threading.Event:
        return self._event

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> None:
        with self._lock:
            if not self._reason:
                self._reason = reason
            self._event.set()
            children = list(self._children)
        for child in children:
            child.cancel(reason)


class CallProgress:
    """Worker-side progress beacon for stale-call detection."""

    __slots__ = ("_last", "_first")

    def __init__(self) -> None:
        self._last = time.perf_counter()
        self._first: float | None = None

    def touch(self) -> None:
        now = time.perf_counter()
        self._last = now
        if self._first is None:
            self._first = now

    def reset(self) -> None:
        self._last = time.perf_counter()
        self._first = None

    @property
    def last(self) -> float:
        return self._last

    @property
    def first(self) -> float | None:
        return self._first


def interruptible_call(
    fn: Callable[[], T],
    interrupt_event: threading.Event,
    *,
    poll_interval: float = 0.1,
    stale_timeout: float | None = None,
    first_progress_timeout_s: float | None = None,
    on_heartbeat: Callable[[float], None] | None = None,
    on_abandon: Callable[[], None] | None = None,
    join_on_abandon: float = 0.0,
    progress: CallProgress | None = None,
    executor: Any = None,
) -> T:
    """Run ``fn()`` on a worker thread while polling interrupt, heartbeat, and stale timers."""
    if interrupt_event.is_set():
        raise AgentInterrupted("agent loop was interrupted before dispatch")
    box: dict[str, Any] = {}
    context = copy_context()

    def _worker() -> None:
        try:
            box["value"] = context.run(fn)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    started = time.perf_counter()
    if executor is not None:
        future = executor.submit(_worker)

        def _is_running() -> bool:
            return not future.done()

        def _wait(timeout: float) -> None:
            try:
                future.result(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass
    else:
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        _is_running = thread.is_alive

        def _wait(timeout: float) -> None:
            thread.join(timeout=timeout)

    def _abandon(exc: BaseException) -> None:
        if on_abandon is not None:
            try:
                on_abandon()
            except Exception:  # noqa: BLE001
                pass
            if join_on_abandon > 0:
                _wait(join_on_abandon)
        elif executor is not None:
            _wait(stale_timeout if stale_timeout else 30.0)
        raise exc

    while _is_running():
        if interrupt_event.is_set():
            _abandon(AgentInterrupted("agent loop was interrupted"))
        elapsed = time.perf_counter() - started
        before_first = progress is None or progress.first is None
        deadline = (
            first_progress_timeout_s
            if before_first and first_progress_timeout_s is not None
            else stale_timeout
        )
        if deadline is not None:
            since_progress = (
                time.perf_counter() - progress.last
                if progress is not None
                else elapsed
            )
            if since_progress > deadline:
                _abandon(
                    StaleCallTimeout(
                        f"no progress for {since_progress:.1f}s "
                        f"({elapsed:.1f}s total, silence_limit={deadline:.0f}s)"
                    )
                )
        if on_heartbeat is not None:
            try:
                on_heartbeat(elapsed)
            except Exception:  # noqa: BLE001
                pass
        _wait(poll_interval)

    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


__all__ = [
    "AgentInterrupted",
    "CallProgress",
    "CancelScope",
    "StaleCallTimeout",
    "interruptible_call",
]
