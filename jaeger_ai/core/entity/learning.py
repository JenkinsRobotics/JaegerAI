"""Learning Layer (UPAA Principle 11).

Converts verified experience into durable, cross-session improvements.

Canonical Flow:
    EXPERIENCE / EVENT
    ──► VERIFICATION / EVIDENCE
    ──► LEARNING DECISION
    ──► UPDATE TARGET SUBSYSTEMS:
          ├─► Episodic Memory (append-only ground-truth log)
          ├─► Semantic Knowledge / World Model (entities, claims, relations)
          ├─► Reflective Memory (meta-cognitive rules, heuristics, failure post-mortems)
          ├─► Skill Library (promoted executable tools/procedures with assertions)
          └─► Strategy Metadata (tool confidence, latency budgets, routing bias)

CONSOLIDATION ≠ LEARNING:
    Consolidation is one offline mechanism (episodic -> semantic/reflective).
    Learning is the broader continuous subsystem responsible for all durable
    adaptations driven by verified real-world evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import time
from typing import Any, Mapping

from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .memory import MemorySubsystem
from .self_state import SelfState
from .verification import VerificationResult, VerificationStatus

logger = logging.getLogger("jaeger.entity.learning")


class LearningTarget(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    WORLD_MODEL = "world_model"
    REFLECTIVE = "reflective"
    SKILL_LIBRARY = "skill_library"
    STRATEGY_METADATA = "strategy_metadata"


@dataclass
class LearningDecision:
    targets: list[LearningTarget]
    rationale: str
    updates_applied: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class LearningPipeline:
    """The continuous learning coordinator converting verified evidence into durable adaptations."""

    def __init__(
        self,
        state_root: Path,
        event_store: SqliteEventStore,
        memory: MemorySubsystem | None = None,
        verification: Any | None = None,
    ) -> None:
        self.state_root = state_root
        self.event_store = event_store
        self.memory = memory or MemorySubsystem(state_root, event_store)
        self.verification = verification

    def record_turn_experience(
        self,
        event: JaegerEvent,
        decision: Any,
        cog_result: Mapping[str, Any],
        verification: VerificationResult,
        reflexion_store: Any | None = None,
        state: SelfState | None = None,
    ) -> LearningDecision:
        """Record turn outcome into episodic, semantic, or reflective memory."""
        # 1. Update episodic record
        self.memory.episodic.record_interaction(
            session_id=event.session_id,
            user_text=str(event.payload.get("text") or ""),
            agent_response=str(cog_result.get("text") or ""),
            tool_calls=cog_result.get("tool_activity") or [],
        )

        # 2. Check for failure to formulate reflection
        if verification.status == VerificationStatus.OBJECTIVE_FAILED or (cog_result.get("error") and verification.error):
            from .reflection import formulate_reflection_from_failure
            refl = formulate_reflection_from_failure(event, verification)
            if reflexion_store is not None:
                reflexion_store.add_reflection(refl)
                try:
                    self.event_store.append(
                        JaegerEvent(
                            event_id="",
                            event_type=EventType.REFLECTION_CREATED.value,
                            actor="system:reflexion",
                            source="learning_pipeline",
                            timestamp=time.time(),
                            session_id=event.session_id,
                            payload={
                                "reflection_id": refl.reflection_id,
                                "hypothesis": refl.hypothesis,
                                "confidence": refl.confidence,
                                "failure_conditions": refl.failure_conditions,
                            },
                            parent_event_id=event.event_id,
                            salience=0.6,
                        )
                    )
                except Exception:
                    pass
            self.memory.reflective.store_insight(
                topic="turn_failure",
                observation=f"Turn on '{event.payload.get('text', '')[:60]}' failed: {verification.error or cog_result.get('error')}",
                implication=refl.hypothesis,
            )

        if state is not None:
            return self.process_experience(event, verification, state)

        return LearningDecision(
            targets=[LearningTarget.EPISODIC],
            rationale="Turn experience recorded to episodic memory",
            updates_applied={"event_id": event.event_id},
        )

    def process_experience(
        self,
        event: JaegerEvent,
        verification: VerificationResult,
        state: SelfState,
    ) -> LearningDecision:
        """Evaluate an experiential consequence and its verification evidence to apply durable updates."""
        targets: list[LearningTarget] = []
        updates: dict[str, Any] = {}

        # 1. Episodic Record is always durable by invariant
        targets.append(LearningTarget.EPISODIC)
        updates["episodic_event_id"] = event.event_id

        # 2. If the consequence was independently verified
        if verification.is_verified:
            # 2a. Semantic / World Model Update
            if event.event_type == EventType.TOOL_COMPLETED.value:
                tool_name = event.payload.get("tool_name", "")
                result = event.payload.get("result")
                # Record verified factual claim
                claim_res = self.memory.semantic.record_claim(
                    subject=f"tool:{tool_name}",
                    predicate="last_verified_outcome",
                    value=str(verification.evidence)[:500],
                    source_id=event.event_id,
                    confidence=1.0,
                )
                targets.append(LearningTarget.SEMANTIC)
                targets.append(LearningTarget.WORLD_MODEL)
                updates["claim"] = claim_res

            # 2b. Skill Candidate Evaluation
            # If a complex tool sequence or script succeeded and verified, submit candidate
            if event.payload.get("is_novel_pattern"):
                targets.append(LearningTarget.SKILL_LIBRARY)
                updates["skill_candidate"] = event.payload.get("tool_name")

            # 2c. Strategy Metadata Update
            targets.append(LearningTarget.STRATEGY_METADATA)
            updates["strategy_confidence"] = "reinforced"

            rationale = f"Objective verified by {verification.verifier}: updating semantic and strategy state"

        elif verification.status == VerificationStatus.OBJECTIVE_FAILED:
            # Objective failed despite possible tool syntactic success -> Reflective Lesson
            ins = self.memory.reflective.store_insight(
                topic="objective_failure",
                observation=f"Action on {event.event_type} failed objective: {verification.evidence}",
                implication="Add pre-condition validation before attempting similar operation",
            )
            targets.append(LearningTarget.REFLECTIVE)
            targets.append(LearningTarget.STRATEGY_METADATA)
            updates["reflective_insight_id"] = ins.insight_id
            updates["strategy_confidence"] = "penalized"
            rationale = f"Objective verification failed ({verification.error}): generated reflective lesson"

        else:
            # Syntactic success only / unverified objective
            rationale = "Action unverified by independent ground-truth: no durable semantic updates applied"

        decision = LearningDecision(
            targets=targets,
            rationale=rationale,
            updates_applied=updates,
        )

        logger.debug(
            "Learning decision for event %s: targets=%s, rationale=%s",
            event.event_id,
            [t.value for t in targets],
            rationale,
        )
        return decision
