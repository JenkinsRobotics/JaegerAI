"""Jaeger Persistent Entity Runtime (Pinocchio Architecture).

Provides a single authoritative persistent entity layer unifying:
- Stable instance identity (model != agent)
- Canonical event schema and durable append-only event log
- Deterministic self-state projection and state reduction
- Lightweight salience / attention gating (passive telemetry vs cognition wake)
- Canonical runtime coordinator unifying turns, tools, memory, and skills
- Explicit authority and policy boundary
- Ground-truth verification separate from effect logging
- 5-part memory taxonomy (working, episodic, semantic, reflective, procedural)
- Executive cognitive strategy selection
- True sleep-time processing (heartbeat as trigger only)
- Continuous learning pipeline (verified evidence -> durable updates)
"""

from .attention import AttentionDecision, SalienceEngine, SalienceLevel
from .authority import (
    AuthorityDecision,
    AuthorityLayer,
    AuthorizationStatus,
    ProposedAction,
)
from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .executive import (
    CognitiveStrategy,
    ExecutiveDecision,
    ExecutiveStrategySelector,
)
from .identity import EntityIdentity
from .learning import (
    LearningDecision,
    LearningPipeline,
    LearningTarget,
)
from .memory import (
    EpisodicMemory,
    MemoryKind,
    MemorySubsystem,
    ProceduralMemory,
    ReflectiveInsight,
    ReflectiveMemory,
    SemanticMemory,
    WorkingMemory,
)
from .reducer import reduce_event, replay_events
from .runtime import EntityRuntime
from .self_state import SelfState
from .cognition_router import (
    CognitionResult,
    CognitionRouter,
)
from .deliberate_planner import (
    CandidatePlan,
    DeliberatePlanner,
)
from .reflection import (
    ReflexionStore,
    StructuredReflection,
    formulate_reflection_from_failure,
)
from .self_refine import (
    SelfRefineEngine,
    SelfRefineResult,
)
from .sleep_time import (
    SleepCycleResult,
    SleepTimeJobType,
    SleepTimeProcessor,
)
from .verification import (
    VerificationContract,
    VerificationResult,
    VerificationStatus,
)

__all__ = [
    "AttentionDecision",
    "AuthorityDecision",
    "AuthorityLayer",
    "AuthorizationStatus",
    "CandidatePlan",
    "CognitionResult",
    "CognitionRouter",
    "CognitiveStrategy",
    "DeliberatePlanner",
    "EntityIdentity",
    "EntityRuntime",
    "EpisodicMemory",
    "EventType",
    "ExecutiveDecision",
    "ExecutiveStrategySelector",
    "JaegerEvent",
    "LearningDecision",
    "LearningPipeline",
    "LearningTarget",
    "MemoryKind",
    "MemorySubsystem",
    "ProceduralMemory",
    "ProposedAction",
    "ReflectiveInsight",
    "ReflectiveMemory",
    "ReflexionStore",
    "SalienceEngine",
    "SalienceLevel",
    "SelfRefineEngine",
    "SelfRefineResult",
    "SelfState",
    "SemanticMemory",
    "SleepCycleResult",
    "SleepTimeJobType",
    "SleepTimeProcessor",
    "SqliteEventStore",
    "StructuredReflection",
    "VerificationContract",
    "VerificationResult",
    "VerificationStatus",
    "WorkingMemory",
    "formulate_reflection_from_failure",
    "reduce_event",
    "replay_events",
]
