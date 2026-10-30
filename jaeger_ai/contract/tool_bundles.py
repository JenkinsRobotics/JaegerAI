"""Tool bundles — named, contract-level groupings of agent tools.

A **bundle** is the unit of goal-aligned tool access. An operator's goal
declares ``tool_bundle: "robotics.build"`` and the Gateway intersects that
bundle with the assigned agent's enforced allowlist
(``AgentRecord.metadata["tool_allowlist"]``) at turn admission. The
intersection is enforced by the existing :class:`AllowlistToolExecutor`
plus the ``tool_allowlist`` ContextVar — *no new permission code*.

Per AGENTS.md §5 ("one definition per fact"), every bundle is defined
exactly once here and imported wherever it is needed. Never retype a
tool name in a second place.

Semantics:

- A bundle is a **cap, not a grant**. ``bundle ∩ agent_allowlist`` is what
  the agent may call. An agent whose allowlist is ``None`` (inherit) is
  capped to the bundle; an agent with an explicit list is capped to the
  intersection; a CHARACTER agent (``[]``, enforced no-tools) stays at
  zero no matter what bundle a goal declares.
- Bundles are fine-grained on purpose: ``robotics.deploy`` must never
  ride along with ``robotics.build``. Grant the narrow bundle.
"""

from __future__ import annotations

from typing import Final

#: Bundle name → tool names it may reach. Names must match the registry
#: exactly (``register_tool_from_function`` derives them from the function
#: name). Globs (``mcp__x__*``) are expanded by
#: ``jaeger_ai.core.agent_registry.specialists.expand_tool_patterns``.
TOOL_BUNDLES: Final[dict[str, frozenset[str]]] = {
    # Goal management — safe, read-mostly. Wide bundle: any agent that
    # works toward a goal needs to see and update its state.
    "goals": frozenset({
        "goal_create", "goal_list", "goal_status", "goal_update",
        "project_status", "task_spawn",
    }),
    # Robotics / hardware project work. Split so build never implies deploy.
    "robotics.build": frozenset({
        "robotics_build", "nas_backup",
    }),
    "robotics.deploy": frozenset({
        "robotics_deploy",
    }),
    # Content pipeline (YouTube studio) — script → roughcut → publish.
    "content": frozenset({
        "content_pipeline",
    }),
    # Daily operator briefing — read-only composition of existing tools.
    "briefing": frozenset({
        "morning_briefing",
    }),
}


def bundle_tools(name: str) -> frozenset[str]:
    """Return the tool set for a bundle, or an empty set for an unknown
    bundle name. Unknown bundles fail CLOSED — a typo must not widen
    access."""
    return TOOL_BUNDLES.get(name, frozenset())


def is_known_bundle(name: str) -> bool:
    return name in TOOL_BUNDLES


__all__ = ["TOOL_BUNDLES", "bundle_tools", "is_known_bundle"]
