"""ARES: Autonomous Reasoning and Execution System.

A self-contained cognitive subsystem within the JaegerAI agent framework.
Implements continuous perception, unbroken episodic context, endogenous
intent formation, medium-agnostic transduction, and epistemic learning.
"""

from __future__ import annotations

from .belief import BeliefState, EpistemicContext
from .engine import ARESConfig, ARESEngine, ARESResult
from .intent import CognitiveIntent, IntentKind, MediumType
from .perception import PerceptionSnapshot, SensorStream

__all__ = [
    "ARESConfig",
    "ARESEngine",
    "ARESResult",
    "BeliefState",
    "CognitiveIntent",
    "EpistemicContext",
    "IntentKind",
    "MediumType",
    "PerceptionSnapshot",
    "SensorStream",
]
