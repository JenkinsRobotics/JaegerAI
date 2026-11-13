"""jaeger_ai/contract/modes.py — Authoritative interaction tiers and presence contracts.

Defines the work styles in JaegerAI:
  1. "chat"  — Conversational & memory-aware. Responds only when prompted; text-only, no tools.
  2. "agent" — Task worker. Bounded ReAct tool loop (shell/files/git) under autonomy policy.
  3. "plan"  — Read-only tools; the model researches and ends with a plan for approval.
               The owner switches to Agent to execute. Write and exec tools are blocked.

The former "jaeger" resident/always-on run mode has been removed. Saved
values of "jaeger" are read as "agent".

Defined here, once, because Gateway, WebUI, IDE, TUI, and settings schema all consult it.
"""
from __future__ import annotations

import re
from typing import Final, Literal

InteractionTier = Literal["chat", "agent", "plan"]

INTERACTION_TIERS: Final[tuple[InteractionTier, ...]] = ("chat", "agent", "plan")
DEFAULT_INTERACTION_TIER: Final[InteractionTier] = "agent"
# Retired run-mode value; never offered, always read as Agent.
RETIRED_INTERACTION_TIERS: Final[frozenset[str]] = frozenset({"jaeger"})

TIER_NUMBERS: Final[dict[InteractionTier, int]] = {
    "chat": 1,
    "plan": 2,
    "agent": 3,
}

TIER_NAMES: Final[dict[int, InteractionTier]] = {
    1: "chat",
    2: "plan",
    3: "agent",
}

TIER_DESCRIPTIONS: Final[dict[InteractionTier, str]] = {
    "chat": "Conversational only; no tool execution.",
    "agent": "Task worker; runs tools under the approval policy until the task is done or the fuse trips.",
    "plan": "Read-only tools; Jaeger researches and writes a plan for you to approve before anything is changed.",
}

PLAN_MODE_NOTE = (
    "[Plan mode]\n"
    "This turn is for planning only. You may use read-only tools (read, list, "
    "search, inspect) to understand the workspace and the request. You must not "
    "write, edit, delete, run commands, send messages, or otherwise change "
    "anything. End your turn with a clear plan the owner can approve: short "
    "steps, in order, of what Agent mode should do. Do not claim that any "
    "change already happened. The owner will switch to Agent mode to execute."
)

# Deny wins. Plan mode is read/inspect only.
_PLAN_DENY = re.compile(
    r"(write|edit|patch|delete|remove|\brm\b|mkdir|rmdir|unlink|move|rename|"
    r"exec|shell|bash|zsh|\bsh\b|terminal|command|run_|spawn|install|pip|"
    r"npm|kill|chmod|chown|push|commit|rebase|merge|deploy|send_|mail|"
    r"cron|schedule|grant|approv|transfer|delegate|call_agent|browser_click|"
    r"computer_do|computer_use)",
    re.I,
)

EntityPresence = Literal[
    "dormant",      # Chat mode / sleeping
    "idle",         # Agent mode / idle between tasks
    "observing",    # Listening to sensors, zero LLM calls (not a run-mode)
    "deliberating", # Evaluating salience and planning
    "executing",    # Running tool pipeline via GatewayTaskOwner
    "waiting",      # Awaiting operator approval or input
]


def normalize_interaction_tier(value: str | None) -> InteractionTier:
    """Public work style. Retired 'jaeger' (resident mode) becomes Agent."""
    raw = (value or "").strip().lower()
    if raw in RETIRED_INTERACTION_TIERS:
        return "agent"
    if raw in INTERACTION_TIERS:
        return raw  # type: ignore[return-value]
    return DEFAULT_INTERACTION_TIER


def plan_tool_allowed(name: str) -> bool:
    """True when this tool may run in Plan mode (read/inspect only)."""
    tool = str(name or "").strip()
    if not tool:
        return False
    return _PLAN_DENY.search(tool) is None


def plan_mode_system_prompt(system_prompt: str | None) -> str:
    """Append the Plan-mode contract to the base system prompt."""
    base = (system_prompt or "").rstrip()
    if PLAN_MODE_NOTE in base:
        return base
    return f"{base}\n\n{PLAN_MODE_NOTE}" if base else PLAN_MODE_NOTE


__all__ = [
    "DEFAULT_INTERACTION_TIER",
    "EntityPresence",
    "INTERACTION_TIERS",
    "InteractionTier",
    "PLAN_MODE_NOTE",
    "RETIRED_INTERACTION_TIERS",
    "TIER_DESCRIPTIONS",
    "TIER_NAMES",
    "TIER_NUMBERS",
    "normalize_interaction_tier",
    "plan_mode_system_prompt",
    "plan_tool_allowed",
]
