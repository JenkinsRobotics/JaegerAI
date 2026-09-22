"""Memory Provenance Classifications for Context Compilation (Workstream 6).

Core Invariant:
Remembered facts, observations, reflections, and retrieved docs must NEVER
be blurred into an undifferentiated prompt blob. Every context fragment retains
its explicit provenance.
"""
from __future__ import annotations

from enum import Enum


class MemoryProvenance(str, Enum):
    IDENTITY = "PROVENANCE_IDENTITY"
    SELF_STATE = "PROVENANCE_SELF_STATE"
    RUNTIME_TRUTH = "PROVENANCE_RUNTIME_TRUTH"
    EPISODIC_EVENT = "PROVENANCE_EPISODIC_EVENT"
    SEMANTIC_CLAIM = "PROVENANCE_SEMANTIC_CLAIM"
    REFLEXION = "PROVENANCE_REFLEXION"
    RETRIEVED_DOCUMENT = "PROVENANCE_RETRIEVED_DOCUMENT"
    LEARNED_SKILL = "PROVENANCE_LEARNED_SKILL"
    CAPABILITY_STATE = "PROVENANCE_CAPABILITY_STATE"
    CONVERSATION_HISTORY = "PROVENANCE_CONVERSATION_HISTORY"
    DEVICE_OBSERVATION = "PROVENANCE_DEVICE_OBSERVATION"
