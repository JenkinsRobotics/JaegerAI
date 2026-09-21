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
from .authority import AuthorityDecision, AuthorityLayer, ProposedAction
from .cognition_router import CognitionRouter
from .deliberate_planner import DeliberatePlanner
from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .executive import CognitiveStrategy, ExecutiveDecision, ExecutiveStrategySelector
from .identity import EntityIdentity, resolve_entity_identity
from .learning import LearningDecision, LearningPipeline
from .memory import MemorySubsystem
from .reducer import reduce_event, replay_events
from .reflection import ReflexionStore
from .self_refine import SelfRefineEngine
from .self_state import SelfState
from .sleep_time import SleepTimeProcessor
from .verification import VerificationContract, VerificationResult

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
        self.executive_selector = ExecutiveStrategySelector()
        self.authority_layer = AuthorityLayer()
        self.verification_contract = VerificationContract()
        self.memory_subsystem = MemorySubsystem(self.state_root, self.event_store)
        self.reflexion_store = ReflexionStore(self.state_root)
        self.learning_pipeline = LearningPipeline(
            self.state_root,
            self.event_store,
            self.memory_subsystem,
            self.verification_contract,
        )
        self.deliberate_planner = DeliberatePlanner()
        self.self_refine_engine = SelfRefineEngine()
        self.sleep_time_processor = SleepTimeProcessor(
            self.state_root,
            self.event_store,
            self.memory_subsystem,
        )
        self.cognition_router = CognitionRouter()

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

    def execute_turn(
        self,
        user_text: str,
        *,
        session_id: str = "dispatcher",
        source: str = "chat",
        actor: str = "human:operator",
        request_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a turn through the sovereign UPAA control path:
        EVENT
        -> EVENT FABRIC
        -> PERSIST
        -> PERCEPTION / STATE REDUCTION
        -> SELF STATE UPDATE
        -> ATTENTION / SALIENCE
        -> EXECUTIVE STRATEGY SELECTION
        -> COGNITION MODE & PROVIDER
        -> PROPOSED ACTION / AUTHORITY
        -> ACTION SYSTEM / ENVIRONMENT
        -> CONSEQUENCE EVENT
        -> VERIFICATION
        -> LEARNING
        -> MEMORY UPDATE
        """
        ctx = dict(context or {})

        # 1. Ingest event to Fabric, reduce SelfState, evaluate Salience
        event = JaegerEvent.human_message(
            user_text,
            actor=actor,
            source=source,
            session_id=session_id,
            request_id=request_id,
        )
        current_state, attention = self.ingest(event)

        # Passive gate: if salience indicates no wake
        if not attention.wake_cognition:
            return {
                "text": "",
                "error": None,
                "tool_activity": [],
                "report": {},
                "skipped_final": False,
                "strategy": CognitiveStrategy.PASSIVE_OBSERVE.value,
                "wake_cognition": False,
            }

        # 2. Executive Strategy Selection
        exec_decision = self.executive_selector.select_strategy(event, current_state)

        # 3. Cognition Router Execution
        ctx["sleep_processor"] = self.sleep_time_processor
        cog_result = self.cognition_router.execute(
            strategy=exec_decision.strategy,
            event=event,
            decision=exec_decision,
            state=current_state,
            memory=self.memory_subsystem,
            authority=self.authority_layer,
            context=ctx,
        )

        response_text = str((cog_result or {}).get("text") or "")

        # 4. Independent Verification
        target_path = (cog_result or {}).get("path") or (cog_result or {}).get("target_path")
        expected_content = (cog_result or {}).get("expected_content")
        verif = self.verification_contract.verify_filesystem_write(
            target_path=target_path,
            expected_content=expected_content,
        )

        # 5. Continuous Learning & Memory Update
        self.learning_pipeline.record_turn_experience(
            event=event,
            decision=exec_decision,
            cog_result=cog_result or {},
            verification=verif,
            reflexion_store=self.reflexion_store,
            state=current_state,
        )

        # 6. Record Agent Response in Event Fabric
        if response_text:
            self.record_agent_response(
                response_text,
                session_id=session_id,
                metadata={
                    "strategy": exec_decision.strategy.value,
                    "plan_id": (cog_result or {}).get("plan_id"),
                },
            )

        # Standard dictionary format for callers
        result_dict = dict(cog_result or {})
        if "tool_activity" not in result_dict:
            result_dict["tool_activity"] = []
        if "error" not in result_dict:
            result_dict["error"] = None
        if "report" not in result_dict:
            result_dict["report"] = {}
        if "skipped_final" not in result_dict:
            result_dict["skipped_final"] = False
        result_dict["strategy"] = exec_decision.strategy.value
        result_dict["text"] = response_text

        return result_dict

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
