"""Jaeger Persistent Entity Runtime (Pinocchio Architecture).

Provides a single authoritative persistent entity layer unifying:
- Stable instance identity (model != agent)
- Canonical event schema and durable append-only event log
- Deterministic self-state projection and state reduction
- Lightweight salience / attention gating (passive telemetry vs cognition wake)
- Canonical runtime coordinator unifying turns, tools, memory, and skills
"""

from .attention import AttentionDecision, SalienceEngine, SalienceLevel
from .events import EventType, JaegerEvent
from .event_store import SqliteEventStore
from .identity import EntityIdentity
from .reducer import reduce_event, replay_events
from .runtime import EntityRuntime
from .self_state import SelfState

__all__ = [
    "AttentionDecision",
    "EntityIdentity",
    "EntityRuntime",
    "EventType",
    "JaegerEvent",
    "SalienceEngine",
    "SalienceLevel",
    "SelfState",
    "SqliteEventStore",
    "reduce_event",
    "replay_events",
]
