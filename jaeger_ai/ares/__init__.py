"""ARES (module path ``jaeger_ai.ares``): experimental endogenous heartbeat cognition.

This package is a self-contained cognitive loop used by Jaeger heartbeat ticks:
continuous perception, unbroken episodic context, endogenous intent formation,
medium-agnostic transduction, and epistemic learning.

Honest naming:
  * Product / archive "ARES" (Agentgateway, ``~/.ares`` runtime) is **not** this
    module. Prefer thinking of this as experimental cognition / heartbeat OODA —
    kept under ``jaeger_ai.ares`` to avoid import churn.
  * This is **not** an AGI/SI replacement. It is a gated, fail-closed helper that
    may suggest or (only when explicitly allowed) perform limited local actions.
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
