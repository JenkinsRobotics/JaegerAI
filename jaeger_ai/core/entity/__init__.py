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
    "CognitiveStrategy",
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
    "SalienceEngine",
    "SalienceLevel",
    "SelfState",
    "SemanticMemory",
    "SleepCycleResult",
    "SleepTimeJobType",
    "SleepTimeProcessor",
    "SqliteEventStore",
    "VerificationContract",
    "VerificationResult",
    "VerificationStatus",
    "WorkingMemory",
    "reduce_event",
    "replay_events",
]
