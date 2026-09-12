"""Reasoning — experimental endogenous heartbeat cognition.

A self-contained cognitive loop driven by Jaeger heartbeat ticks: continuous
perception, unbroken episodic context, endogenous intent formation,
medium-agnostic transduction, and epistemic learning.

What distinguishes this package from every other "thinking" module in the tree
is that it runs **unprompted, on its own clock**. ``jaeger_agent.cognition``
owns the executive around one *user* turn; this owns the tick that fires when
nobody asked.

Naming (renamed from ``jaeger_ai.ares``):
  * It was ARES — Autonomous Reasoning and Execution System. The acronym now
    names the product experience layer, so this package is named for its role
    instead. Same code, same behaviour.
  * The separate ``~/.ares`` product is reached only through
    :mod:`jaeger_ai.core.ares_interop`; it is unrelated to this module and
    keeps its own name.
  * This is **not** an AGI/SI replacement. It is a gated, fail-closed helper
    that may suggest or (only when explicitly allowed) perform limited local
    actions.
"""

from __future__ import annotations

from .belief import BeliefState, EpistemicContext
from .engine import ReasoningConfig, ReasoningEngine, ReasoningResult
from .intent import CognitiveIntent, IntentKind, MediumType
from .perception import PerceptionSnapshot, SensorStream

__all__ = [
    "ReasoningConfig",
    "ReasoningEngine",
    "ReasoningResult",
    "BeliefState",
    "CognitiveIntent",
    "EpistemicContext",
    "IntentKind",
    "MediumType",
    "PerceptionSnapshot",
    "SensorStream",
]
