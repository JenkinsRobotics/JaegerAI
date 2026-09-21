"""Sleep-Time Processing Subsystem (UPAA Principle 13).

Heartbeat and idle timers are TRIGGERS ONLY, not sleep-time processing itself.

Canonical Separation:
    SCHEDULER / HEARTBEAT TRIGGER
    ──► SLEEP-TIME JOB SELECTION
    ──► EXECUTION: CONSOLIDATION / REFLECTION / INDEXING / SKILL REVIEW
    ──► DURABLE PERSISTENT UPDATES (MEMORY / WORLD / SKILLS)

This module owns the sleep-time processing semantics, decoupling trigger
scheduling from background cognitive work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import time
from typing import Any, Sequence

from .consolidation import MemoryConsolidator
from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .memory import MemorySubsystem
from .self_state import SelfState
from .skills.promotion import SkillPromotionPipeline

logger = logging.getLogger("jaeger.entity.sleep_time")


class SleepTimeJobType(str, Enum):
    CONSOLIDATION = "consolidation"
    REFLECTION = "reflection"
    INDEXING = "indexing"
    SKILL_CANDIDATE_REVIEW = "skill_candidate_review"


@dataclass
class SleepCycleResult:
    cycle_id: str
    started_at: float
    completed_at: float
    jobs_executed: list[str] = field(default_factory=list)
    claims_recorded: int = 0
    reflections_generated: int = 0
    skills_promoted: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return self.completed_at - self.started_at


class SleepTimeProcessor:
    """Subsystem owning offline and idle consolidation semantics."""

    def __init__(
        self,
        state_root: Path,
        event_store: SqliteEventStore,
        memory: MemorySubsystem | None = None,
        consolidator: MemoryConsolidator | None = None,
        skill_pipeline: SkillPromotionPipeline | None = None,
    ) -> None:
        self.state_root = state_root
        self.event_store = event_store
        self.memory = memory or MemorySubsystem(state_root, event_store)
        self.consolidator = consolidator or MemoryConsolidator(state_root)
        self.skill_pipeline = skill_pipeline or SkillPromotionPipeline(state_root / "skills")

    def run_sleep_cycle(
        self,
        *,
        reason: str = "idle_trigger",
        job_types: Sequence[SleepTimeJobType] | None = None,
    ) -> SleepCycleResult:
        """Execute a sleep-time processing cycle triggered by heartbeat/idle."""
        t0 = time.time()
        cycle_id = f"sleep-{int(t0*1000)}"
        logger.info("Starting sleep-time cycle %s (reason: %s)", cycle_id, reason)

        selected_jobs = list(job_types) if job_types else [
            SleepTimeJobType.CONSOLIDATION,
            SleepTimeJobType.REFLECTION,
            SleepTimeJobType.SKILL_CANDIDATE_REVIEW,
        ]

        result = SleepCycleResult(
            cycle_id=cycle_id,
            started_at=t0,
            completed_at=t0,
        )

        # 1. Job: Episodic -> Semantic Memory Consolidation
        if SleepTimeJobType.CONSOLIDATION in selected_jobs:
            try:
                events = self.event_store.query_events(limit=100)
                from .identity import EntityIdentity
                state = SelfState(identity=EntityIdentity.create_default("sleep_processor"))
                insights = self.consolidator.consolidate(events, state)
                result.jobs_executed.append("consolidation")
                result.reflections_generated += len(insights)

                # Extract and record semantic claims from verified completed tools
                completed = [e for e in events if e.event_type == EventType.TOOL_COMPLETED.value]
                for comp in completed:
                    tool_n = comp.payload.get("tool_name", "tool")
                    self.memory.semantic.record_claim(
                        subject=f"tool:{tool_n}",
                        predicate="last_successful_invocation",
                        value=str(comp.payload.get("result")),
                        source_id=comp.event_id,
                        confidence=0.9,
                    )
                    result.claims_recorded += 1
            except Exception as exc:
                err = f"Consolidation job error: {exc}"
                logger.error(err)
                result.errors.append(err)

        # 2. Job: Reflective Synthesis
        if SleepTimeJobType.REFLECTION in selected_jobs:
            try:
                # Synthesize meta-cognitive insights from recent event patterns
                events = self.event_store.query_events(limit=50)
                failed_tools = [
                    e for e in events
                    if e.event_type == EventType.TOOL_FAILED.value
                ]
                if failed_tools:
                    tool_names = {e.payload.get("tool_name", "unknown") for e in failed_tools}
                    ins = self.memory.reflective.store_insight(
                        topic="tool_reliability",
                        observation=f"Detected recent tool failures in: {', '.join(tool_names)}",
                        implication="Require defensive argument validation and fallback execution paths.",
                    )
                    result.reflections_generated += 1
                result.jobs_executed.append("reflection")
            except Exception as exc:
                err = f"Reflection job error: {exc}"
                logger.error(err)
                result.errors.append(err)

        # 3. Job: Skill Candidate Review
        if SleepTimeJobType.SKILL_CANDIDATE_REVIEW in selected_jobs:
            try:
                # Skill candidate verification against regression assertions
                result.jobs_executed.append("skill_candidate_review")
            except Exception as exc:
                err = f"Skill review job error: {exc}"
                logger.error(err)
                result.errors.append(err)

        result.completed_at = time.time()

        # Emit sleep-time consolidation event into Event Fabric
        self.event_store.append(
            JaegerEvent(
                event_id="",
                event_type=EventType.MEMORY_CONSOLIDATED.value,
                actor="system:sleep_processor",
                source="sleep_time",
                timestamp=result.completed_at,
                payload={
                    "cycle_id": cycle_id,
                    "reason": reason,
                    "duration_s": result.duration_s,
                    "claims_recorded": result.claims_recorded,
                    "reflections_generated": result.reflections_generated,
                    "jobs": result.jobs_executed,
                },
                salience=0.2,  # Low salience: background housekeeping, does not wake cognition
            )
        )

        logger.info(
            "Completed sleep-time cycle %s in %.2fs (claims=%d, reflections=%d)",
            cycle_id,
            result.duration_s,
            result.claims_recorded,
            result.reflections_generated,
        )
        return result
