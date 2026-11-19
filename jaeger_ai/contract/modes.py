"""jaeger_ai/contract/modes.py — Authoritative interaction tiers and presence contracts.

Defines the work styles in JaegerAI:
  1. "agent" — Normal conversation: answer directly or use tools under autonomy policy.
  2. "plan"  — Read-only tools; the model researches and ends with a plan for approval.
               The owner switches to Agent to execute. Write and exec tools are blocked.

The former "chat" tool-free and "jaeger" resident run modes have been removed.
Saved values of either are read as "agent". Tool grants and action permissions
are enforced separately; selecting a work style does not override them.

Defined here, once, because Gateway, WebUI, IDE, TUI, and settings schema all consult it.
"""
from __future__ import annotations

import re
from typing import Final, Literal

InteractionTier = Literal["agent", "plan"]

INTERACTION_TIERS: Final[tuple[InteractionTier, ...]] = ("agent", "plan")
DEFAULT_INTERACTION_TIER: Final[InteractionTier] = "agent"
# Retired run-mode value; never offered, always read as Agent.
RETIRED_INTERACTION_TIERS: Final[frozenset[str]] = frozenset({"chat", "jaeger"})

TIER_NUMBERS: Final[dict[InteractionTier, int]] = {
    "plan": 2,
    "agent": 3,
}

TIER_NAMES: Final[dict[int, InteractionTier]] = {
    2: "plan",
    3: "agent",
}

TIER_DESCRIPTIONS: Final[dict[InteractionTier, str]] = {
    "agent": "Normal conversation; answers directly or uses tools under the approval policy.",
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
# Short verbs are word-bounded so "skill" is not denied by "kill",
# "list_skill_dir" stays a read/inspect tool, and instance files remain
# listable in Plan as well as Agent.
_PLAN_DENY = re.compile(
    r"(write|edit|patch|delete|remove|\brm\b|mkdir|rmdir|unlink|\bmove\b|\brename\b|"
    r"exec|shell|bash|zsh|\bsh\b|terminal|command|run_|spawn|install|\bpip\b|"
    r"\bnpm\b|\bkill\b|chmod|chown|\bpush\b|commit|rebase|merge|deploy|send_|"
    r"\bmail\b|cron|schedule|\bgrant\b|approv|transfer|delegate|call_agent|"
    r"browser_click|computer_do|computer_use)",
    re.I,
)

# Read/inspect tools that must stay available in every tool-using mode,
# including listing Jaeger's own skills and instance files.
_PLAN_ALLOW = frozenset({
    "list_skill_dir", "list_skills", "list_tools", "read_file", "search_files",
    "glob", "web_search", "web_extract", "x_search", "get_time", "get_weather",
    "memory", "recall", "user_profile", "describe_tool", "load_tools",
    "tool_search", "calculate",
})

EntityPresence = Literal[
    "dormant",      # Sleeping
    "idle",         # Agent mode / idle between tasks
    "observing",    # Listening to sensors, zero LLM calls (not a run-mode)
    "deliberating", # Evaluating salience and planning
    "executing",    # Running tool pipeline via GatewayTaskOwner
    "waiting",      # Awaiting operator approval or input
]


def normalize_interaction_tier(value: str | None) -> InteractionTier:
    """Public work style. Retired modes become the normal Agent conversation."""
    raw = (value or "").strip().lower()
    if raw in RETIRED_INTERACTION_TIERS:
        return "agent"
    if raw in INTERACTION_TIERS:
        return raw  # type: ignore[return-value]
    return DEFAULT_INTERACTION_TIER


# Authoring / write tools whose names don't match the verb regex
# (skill_manage would otherwise sneak through after "kill" was bounded).
_PLAN_DENY_NAMES = frozenset({
    "skill_manage", "record_skill_revision", "write_file", "append_file",
    "delete_file", "patch", "terminal", "execute_code",
})


def plan_tool_allowed(name: str) -> bool:
    """True when this tool may run in Plan mode (read/inspect only)."""
    tool = str(name or "").strip()
    if not tool:
        return False
    short = tool.split("__")[-1]
    if tool in _PLAN_DENY_NAMES or short in _PLAN_DENY_NAMES:
        return False
    if tool in _PLAN_ALLOW or short in _PLAN_ALLOW:
        return True
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
