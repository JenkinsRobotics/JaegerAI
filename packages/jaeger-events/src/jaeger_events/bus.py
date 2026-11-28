"""Replay-safe typed EventBus implementing EventBusPort.

Harvested donor patterns:
- crewAI (`event_bus.py`): `is_replaying()` ContextVar guard so side-effecting
  listeners (checkpoints, webhooks, notifications) automatically no-op during replay.
- ag2 (`events/base.py`) & agno (`run/base.py`): Monotonically sequenced
  `EventEnvelope` records enabling exact cursor resume (`since_seq`).
- hermes-agent (`plugin_stream_hooks.py`): Fail-isolated listener invocation so
  one crashing observer never breaks the turn hot path.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from jaeger_contracts import EventEnvelope

logger = logging.getLogger("jaeger_events.bus")

_replaying: ContextVar[bool] = ContextVar("jaeger_events_replaying", default=False)


def is_replaying() -> bool:
    """True while EventBus.replay() is actively re-delivering historical events."""
    return _replaying.get()


@contextmanager
def replay_scope() -> Iterator[None]:
    token = _replaying.set(True)
    try:
        yield
    finally:
        _replaying.reset(token)


class HandlerCycleError(ValueError):
    """Raised when a subscribed event handler creates a dependency cycle."""


class StaleWriterError(RuntimeError):
    """Raised when a fenced zombie worker attempts to write/close a superseded run."""


@dataclass
class _Subscription:
    event_type: str
    handler: Callable[[EventEnvelope], None]
    skip_on_replay: bool = False
    name: str = ""
    depends_on: tuple[str, ...] = ()


def _topo_order(subs: list[_Subscription]) -> list[_Subscription]:
    """Order subscriptions respecting ``depends_on`` (CrewAI HandlerGraph pattern)."""
    if not any(s.depends_on for s in subs):
        return subs
    by_name = {s.name: i for i, s in enumerate(subs) if s.name}
    in_deg = [0] * len(subs)
    adj: dict[int, list[int]] = defaultdict(list)
    for idx, sub in enumerate(subs):
        for dep in sub.depends_on:
            parent = by_name.get(dep)
            if parent is not None and parent != idx:
                adj[parent].append(idx)
                in_deg[idx] += 1
    ready = deque(i for i, d in enumerate(in_deg) if d == 0)
    ordered: list[_Subscription] = []
    while ready:
        cur = ready.popleft()
        ordered.append(subs[cur])
        for nxt in adj.get(cur, ()):
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                ready.append(nxt)
    if len(ordered) != len(subs):
        raise HandlerCycleError("Cyclic event handler dependency detected")
    return ordered


class FencedEventStream:
    """Monotonic, writer-generation-fenced event stream (Agno event_streams pattern).

    Guarantees:
    - ``seq`` is strictly monotonic per run and never resets to 0 on resume (``reopen(floor=...)``).
    - Stalled zombie workers holding an older ``generation`` are rejected with ``StaleWriterError``.
    - Contradicted retries can drop buffered events via ``reset_events(generation)`` without
      rolling back the monotonic sequence counter.
    """

    def __init__(self, *, max_events_per_run: int = 4096) -> None:
        self._lock = threading.RLock()
        self._max_events = max(32, int(max_events_per_run))
        self._generation: dict[str, int] = defaultdict(int)
        self._seq: dict[str, int] = defaultdict(int)
        self._closed: dict[str, bool] = defaultdict(bool)
        self._events: dict[str, deque[EventEnvelope]] = defaultdict(
            lambda: deque(maxlen=self._max_events)
        )

    def open_attempt(self, run_id: str, *, floor_seq: int = 0) -> int:
        """Start a new writer generation for ``run_id``; returns the fencing generation."""
        with self._lock:
            self._generation[run_id] += 1
            if floor_seq > self._seq[run_id]:
                self._seq[run_id] = int(floor_seq)
            self._closed[run_id] = False
            return self._generation[run_id]

    def reopen(self, run_id: str, *, floor_seq: int) -> int:
        """Resume a paused run above its persisted DB floor without resetting seq."""
        return self.open_attempt(run_id, floor_seq=floor_seq)

    def current_generation(self, run_id: str) -> int:
        with self._lock:
            return self._generation.get(run_id, 0)

    def append(
        self,
        run_id: str,
        generation: int,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        session_id: str = "default",
        durable: bool = True,
        trace_id: str = "",
        span_id: str = "",
    ) -> EventEnvelope:
        with self._lock:
            current = self._generation.get(run_id, 0)
            if generation != current or self._closed.get(run_id, False):
                raise StaleWriterError(
                    f"Writer generation {generation} fenced out for run {run_id!r} (current={current})"
                )
            self._seq[run_id] += 1
            env = EventEnvelope(
                seq=self._seq[run_id],
                event_type=event_type,
                payload=dict(payload),
                session_id=session_id,
                trace_id=trace_id,
                span_id=span_id,
                durable=durable,
            )
            if durable:
                self._events[run_id].append(env)
            return env

    def reset_events(self, run_id: str, generation: int) -> None:
        """Drop buffered events on retry while preserving the monotonic seq counter."""
        with self._lock:
            current = self._generation.get(run_id, 0)
            if generation != current:
                raise StaleWriterError(f"Writer generation {generation} fenced out for run {run_id!r}")
            self._events[run_id].clear()

    def close_attempt(self, run_id: str, generation: int) -> None:
        with self._lock:
            current = self._generation.get(run_id, 0)
            if generation != current:
                raise StaleWriterError(f"Writer generation {generation} cannot close run {run_id!r}")
            self._closed[run_id] = True

    def read_since(self, run_id: str, *, after_seq: int = 0) -> list[EventEnvelope]:
        with self._lock:
            return [ev for ev in self._events.get(run_id, ()) if ev.seq > after_seq]


class EventBus:
    """Thread-safe, sequenced, replay-aware event bus satisfying EventBusPort."""

    def __init__(self, *, name: str = "jaeger_events", max_history_per_session: int = 2048) -> None:
        self._name = name
        self._max_history = max(16, int(max_history_per_session))
        self._lock = threading.RLock()
        self._seq_by_session: dict[str, int] = defaultdict(int)
        self._history: dict[str, deque[EventEnvelope]] = defaultdict(
            lambda: deque(maxlen=self._max_history)
        )
        self._subs: dict[str, list[_Subscription]] = defaultdict(list)
        self._listener_errors: int = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def listener_errors(self) -> int:
        return self._listener_errors

    def publish(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        session_id: str = "default",
        durable: bool = True,
        trace_id: str = "",
        span_id: str = "",
    ) -> EventEnvelope:
        with self._lock:
            self._seq_by_session[session_id] += 1
            seq = self._seq_by_session[session_id]
            envelope = EventEnvelope(
                seq=seq,
                event_type=event_type,
                payload=dict(payload),
                session_id=session_id,
                trace_id=trace_id,
                span_id=span_id,
                durable=durable,
            )
            if durable:
                self._history[session_id].append(envelope)
            targets = list(self._subs.get(event_type, ())) + list(self._subs.get("*", ()))

        self._dispatch(envelope, targets)
        return envelope

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[EventEnvelope], None],
        *,
        skip_on_replay: bool = False,
        name: str = "",
        depends_on: tuple[str, ...] = (),
    ) -> Callable[[], None]:
        sub = _Subscription(
            event_type=event_type,
            handler=handler,
            skip_on_replay=skip_on_replay,
            name=name,
            depends_on=tuple(depends_on),
        )
        with self._lock:
            candidate = [*self._subs[event_type], sub]
            # Validate DAG eagerly at registration time (CrewAI HandlerGraph)
            self._subs[event_type] = _topo_order(candidate)

        def unsubscribe() -> None:
            with self._lock:
                items = self._subs.get(event_type)
                if items and sub in items:
                    items.remove(sub)

        return unsubscribe

    def history(self, session_id: str = "default", *, since_seq: int = 0) -> list[EventEnvelope]:
        with self._lock:
            return [ev for ev in self._history.get(session_id, ()) if ev.seq > since_seq]

    def replay(self, session_id: str = "default", *, since_seq: int = 0) -> int:
        """Re-deliver durable events after `since_seq` with `is_replaying() == True`."""
        events = self.history(session_id, since_seq=since_seq)
        with replay_scope():
            for ev in events:
                with self._lock:
                    targets = list(self._subs.get(ev.event_type, ())) + list(self._subs.get("*", ()))
                self._dispatch(ev, targets)
        return len(events)

    def _dispatch(self, envelope: EventEnvelope, targets: list[_Subscription]) -> None:
        replaying_now = is_replaying()
        for sub in targets:
            if replaying_now and sub.skip_on_replay:
                continue
            try:
                sub.handler(envelope)
            except Exception:
                with self._lock:
                    self._listener_errors += 1
                logger.exception("Event listener failed for %r (isolated)", envelope.event_type)
