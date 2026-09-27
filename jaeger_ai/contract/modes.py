"""jaeger_ai/contract/modes.py — Authoritative interaction tiers and presence contracts.

Defines the three tiers of agency in JaegerAI:
  1. "chat"   — Conversational & memory-aware. Responds only when prompted; text-only, no tools.
  2. "agent"  — Task worker. Bounded ReAct tool loop (shell/files/git) under autonomy policy.
  3. "jaeger" — Resident entity. Awake, event-driven (sensors/heartbeat), durable tasks, self-reconciling.

Defined here, once, because Gateway, WebUI, IDE, TUI, and settings schema all consult it.
"""
from __future__ import annotations

from typing import Final, Literal

InteractionTier = Literal["chat", "agent", "jaeger"]

INTERACTION_TIERS: Final[tuple[InteractionTier, ...]] = ("chat", "agent", "jaeger")
DEFAULT_INTERACTION_TIER: Final[InteractionTier] = "agent"

TIER_NUMBERS: Final[dict[InteractionTier, int]] = {
    "chat": 1,
    "agent": 2,
    "jaeger": 3,
}

TIER_NAMES: Final[dict[int, InteractionTier]] = {
    1: "chat",
    2: "agent",
    3: "jaeger",
}

TIER_DESCRIPTIONS: Final[dict[InteractionTier, str]] = {
    "chat": "Conversational only; memory-aware, no tool execution, sleeps between turns",
    "agent": "Task worker; runs tools under autonomy policy until task complete or fuse",
    "jaeger": "Resident entity; continuous daemon, event-driven perception, durable proactive tasks",
}

EntityPresence = Literal[
    "dormant",      # Chat mode / sleeping
    "idle",         # Agent mode / idle between tasks
    "observing",    # Jaeger mode / listening to sensors, zero LLM calls
    "deliberating", # Jaeger mode / evaluating salience and planning
    "executing",    # Running tool pipeline via GatewayTaskOwner
    "waiting",      # Awaiting operator approval or input
]

__all__ = [
    "DEFAULT_INTERACTION_TIER",
    "EntityPresence",
    "INTERACTION_TIERS",
    "InteractionTier",
    "TIER_DESCRIPTIONS",
    "TIER_NAMES",
    "TIER_NUMBERS",
]
