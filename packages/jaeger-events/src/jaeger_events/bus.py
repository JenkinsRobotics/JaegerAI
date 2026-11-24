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


@dataclass
class _Subscription:
    event_type: str
    handler: Callable[[EventEnvelope], None]
    skip_on_replay: bool = False


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
    ) -> Callable[[], None]:
        sub = _Subscription(event_type=event_type, handler=handler, skip_on_replay=skip_on_replay)
        with self._lock:
            self._subs[event_type].append(sub)

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
