"""The Canonical Entity Runtime for Jaeger (Pinocchio Architecture).

Implements the single authoritative entity runtime loop:
    EVENT ──► PERSIST ──► UPDATE SELF/WORLD STATE ──► ATTENTION/SALIENCE
                                                          │
                         ┌────────────────────────────────┴────────────────────────┐
                         │                                                         │
               [Salience < Threshold]                                    [Salience >= Threshold]
                         │                                                         │
                   Silent Record                                               Cognition
                  (Zero LLM Calls)                                                 │
                                                                                   ▼
                                                                                 Action
                                                                                   │
                                                                                   ▼
                                                                          Observe Consequence
                                                                                   │
                                                                                   ▼
                                                                           Consequence Event
                                                                                   │
                                                                                   ▼
                                                                            Memory / Learning
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable

from jaeger_ai.core.instance.instance import operator_state_root
from .attention import AttentionDecision, SalienceEngine
from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .identity import EntityIdentity, resolve_entity_identity
from .reducer import reduce_event, replay_events
from .self_state import SelfState

logger = logging.getLogger("jaeger.entity.runtime")


class EntityRuntime:
    """The canonical runtime authority for a persistent Jaeger instance."""

    _instance: EntityRuntime | None = None
    _lock = threading.RLock()

    def __init__(
        self,
        state_root: Path | str | None = None,
        identity: EntityIdentity | None = None,
        event_store: SqliteEventStore | None = None,
        salience_engine: SalienceEngine | None = None,
    ) -> None:
        self.state_root = Path(state_root) if state_root else operator_state_root()
        self.state_root.mkdir(parents=True, exist_ok=True)

        self.identity = identity or resolve_entity_identity(self.state_root)
        self.event_store = event_store or SqliteEventStore(self.state_root / "entity_events.sqlite3")
        self.salience_engine = salience_engine or SalienceEngine()

        # Reconstruct initial state from cold boot replay
        base_state = SelfState(
            identity=self.identity,
            boot_timestamp=time.time(),
        )
        self._state = replay_events(base_state, self.event_store.replay_all())
        self._state_lock = threading.RLock()
        self._cognition_handlers: list[Callable[[JaegerEvent, SelfState], Any]] = []

        logger.info(
            "Initialized EntityRuntime for %s (%s) with %d replayed events",
            self.identity.display_name,
            self.identity.entity_id,
            self._state.total_events_processed,
        )

    @classmethod
    def get_singleton(cls, state_root: Path | str | None = None) -> EntityRuntime:
        """Process-wide singleton instance of the EntityRuntime."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(state_root=state_root)
            return cls._instance

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset singleton reference (for test isolation)."""
        with cls._lock:
            cls._instance = None

    @property
    def current_state(self) -> SelfState:
        with self._state_lock:
            return self._state

    def register_cognition_handler(
        self, handler: Callable[[JaegerEvent, SelfState], Any]
    ) -> None:
        """Register a handler to be invoked when an event triggers cognition wake."""
        self._cognition_handlers.append(handler)

    def ingest(self, event: JaegerEvent) -> tuple[SelfState, AttentionDecision]:
        """Core Invariant Execution Loop:

        1. PERSIST event durably to event store.
        2. UPDATE SelfState deterministically via reducer.
        3. EVALUATE Attention/Salience.
        4. WAKE cognition if required.
        """
        # 1. Persist
        persisted = self.event_store.append(event)

        # 2. Update SelfState
        with self._state_lock:
            self._state = reduce_event(self._state, persisted)
            current_state = self._state

        # 3. Attention / Salience Evaluation
        decision = self.salience_engine.evaluate(persisted, current_state)

        # 4. Trigger cognition handlers if salient
        if decision.wake_cognition:
            for handler in self._cognition_handlers:
                try:
                    handler(persisted, current_state)
                except Exception as exc:
                    logger.error("Cognition handler failed for event %s: %s", persisted.event_id, exc)

        return current_state, decision

    # ── Specialized Ingress Helpers ───────────────────────────────────

    def submit_human_message(
        self,
        text: str,
        *,
        actor: str = "human:operator",
        source: str = "chat",
        session_id: str = "dispatcher",
        request_id: str | None = None,
    ) -> tuple[JaegerEvent, AttentionDecision]:
        event = JaegerEvent.human_message(
            text,
            actor=actor,
            source=source,
            session_id=session_id,
            request_id=request_id,
        )
        _, decision = self.ingest(event)
        return event, decision

    def submit_heartbeat(
        self,
        *,
        source: str = "runtime.heartbeat",
        payload: dict[str, Any] | None = None,
    ) -> tuple[JaegerEvent, AttentionDecision]:
        event = JaegerEvent.heartbeat(source=source, payload=payload)
        _, decision = self.ingest(event)
        return event, decision

    def submit_observation(
        self,
        sensor: str,
        signals: dict[str, Any],
        *,
        salience: float = 0.2,
        session_id: str = "system",
    ) -> tuple[JaegerEvent, AttentionDecision]:
        event = JaegerEvent.perception_sensed(
            sensor,
            signals,
            salience=salience,
            session_id=session_id,
        )
        _, decision = self.ingest(event)
        return event, decision

    def record_tool_start(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        call_id: str,
        session_id: str = "dispatcher",
        actor: str = "agent:jaeger",
    ) -> JaegerEvent:
        event = JaegerEvent.tool_started(
            tool_name,
            arguments,
            call_id=call_id,
            session_id=session_id,
            actor=actor,
        )
        self.ingest(event)
        return event

    def record_tool_result(
        self,
        tool_name: str,
        result: Any,
        *,
        call_id: str,
        duration_s: float,
        session_id: str = "dispatcher",
        error: str | None = None,
    ) -> JaegerEvent:
        if error:
            event = JaegerEvent.tool_failed(
                tool_name,
                error,
                call_id=call_id,
                duration_s=duration_s,
                session_id=session_id,
            )
        else:
            event = JaegerEvent.tool_completed(
                tool_name,
                result,
                call_id=call_id,
                duration_s=duration_s,
                session_id=session_id,
            )
        self.ingest(event)
        return event

    def record_agent_response(
        self,
        text: str,
        *,
        session_id: str = "dispatcher",
        actor: str = "agent:jaeger",
        model: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> JaegerEvent:
        event = JaegerEvent(
            event_id="",
            event_type=EventType.AGENT_RESPONSE.value,
            actor=actor,
            source="runtime.cognition",
            timestamp=time.time(),
            session_id=session_id,
            payload={"text": text, "model": model, **(metadata or {})},
            salience=0.5,
        )
        self.ingest(event)
        return event

    def record_background_completed(
        self,
        task_id: str,
        result: Any,
        *,
        session_id: str = "dispatcher",
        error: str | None = None,
        requires_followup: bool = False,
    ) -> JaegerEvent:
        event = JaegerEvent(
            event_id="",
            event_type=EventType.BACKGROUND_COMPLETED.value,
            actor="system:background",
            source="runtime.background",
            timestamp=time.time(),
            session_id=session_id,
            payload={
                "task_id": task_id,
                "result": result,
                "error": error,
                "requires_followup": requires_followup,
            },
            salience=0.7 if requires_followup else 0.3,
        )
        self.ingest(event)
        return event
