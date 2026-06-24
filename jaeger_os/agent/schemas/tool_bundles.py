"""Toolsets — group tools into named bundles so only the relevant
subset shows up in the model's tool catalogue per turn.

The Hermes pattern: every tool is tagged with a category, and the
agent loop only renders the tools belonging to the *active* toolsets.
For JROS that win is concrete — exposing ~80 tools every turn burns
~10K tokens of the 16K context just on schema, before any history or
results. Restricting to `{essentials, files, web}` drops that to
~2-3K and reclaims headroom for actual conversation.

Two surfaces:

  • :data:`JAEGER_TOOLSETS` — the canonical map of toolset name →
    (description, tool names, included toolsets). Centralised here
    rather than tagged on each ``ToolDef`` so adding a new toolset
    doesn't require touching 63 ``@register_tool_from_function`` sites
    in ``main.py``.

  • :func:`resolve_toolsets` — expand a set of toolset names to the
    union of tool names they contain. The agent loop's filter calls
    this once at format time.

Composition with ``includes`` mirrors Hermes' resolve algorithm so
``"default"`` can fan out to several atomic toolsets without
duplicating the tool lists.

Phase-7 first cut: opinionated defaults that match JROS's typical
chat-assistant workload. Toolsets evolve with usage data — the
``/runtime`` panel will eventually show "tools picked per toolset"
heatmaps so the splits track real routing behaviour.
"""

from __future__ import annotations

from typing import Any


# A *toolset definition*. ``includes`` references other toolsets by
# name; the resolver recurses (with cycle detection). ``description``
# is human-readable for ``/toolsets`` / ``/runtime`` panels.
class ToolsetDef(dict):  # type: ignore[type-arg]
    """Plain dict carrying ``description``, ``tools``, ``includes``.
    Subclassing ``dict`` keeps the literal-style definitions below
    natural to read without a frozendict / dataclass ceremony."""


# ── canonical toolset map ──────────────────────────────────────────


JAEGER_TOOLSETS: dict[str, ToolsetDef] = {
    # ── atomic toolsets ────────────────────────────────────────────
    "time": ToolsetDef(
        description="Current date + time (the model's only source of truth).",
        tools=["get_time"],
        includes=[],
    ),
    "math": ToolsetDef(
        description="Safe arithmetic + expressions.",
        tools=["calculate"],
        includes=[],
    ),
    "host": ToolsetDef(
        description="Machine health, instance metadata, stored credentials.",
        tools=["system_status", "diagnostics", "list_credentials", "get_credential"],
        includes=[],
    ),
    "files": ToolsetDef(
        description="Read / write / patch / delete / list / search the sandboxed workspace.",
        tools=[
            "read_file", "write_file", "append_file", "patch", "delete_file",
            "list_skill_dir", "search_files",
        ],
        includes=[],
    ),
    "web": ToolsetDef(
        description="Web search, content extraction, current weather.",
        tools=["web_search", "web_extract", "get_weather"],
        includes=[],
    ),
    "memory": ToolsetDef(
        description=(
            "The agent's long-term memory across sessions. The umbrella "
            "``memory`` tool covers remember/recall/forget/list/search."
        ),
        # Umbrella + the granular siblings — keep both so we can A/B
        # which the model routes to better. Phase-7 consolidation may
        # drop the siblings (see ``memory_umbrella_only`` below).
        tools=[
            "memory",
            "remember", "recall", "forget", "list_facts", "search_memory",
            "set_name", "update_soul", "read_traits", "adjust_trait",
        ],
        includes=[],
    ),
    "memory_umbrella_only": ToolsetDef(
        description=(
            "Hermes-style memory: ONE umbrella tool with action= dispatch. "
            "Avoids the 'umbrella vs sibling' attractor split that hurt the "
            "bench's L1 routing."
        ),
        tools=["memory", "set_name", "update_soul", "read_traits", "adjust_trait"],
        includes=[],
    ),
    "code": ToolsetDef(
        description="Run Python, run shell, manage the workspace venv + background processes.",
        tools=[
            "execute_code", "terminal", "install_package", "list_venv_packages",
            "run_in_venv", "start_background", "list_background",
            "check_background", "stop_background",
        ],
        includes=[],
    ),
    "schedule": ToolsetDef(
        description="Cron-style scheduling of future prompts.",
        tools=["schedule_prompt", "list_schedules", "cancel_schedule"],
        includes=[],
    ),
    "planning": ToolsetDef(
        description="Within-session todo list + queue deep-think tasks.",
        tools=["todo", "propose_deep_think_task", "list_deep_think_queue"],
        includes=[],
    ),
    "kanban": ToolsetDef(
        description="Cross-session kanban board for durable work.",
        tools=["kanban", "board_view", "board_add", "board_move", "board_update"],
        includes=[],
    ),
    "kanban_umbrella_only": ToolsetDef(
        description="Hermes-style kanban: ONE umbrella tool with action= dispatch.",
        tools=["kanban"],
        includes=[],
    ),
    "browser": ToolsetDef(
        description="Browser automation (navigate, click, type, scroll).",
        tools=["browser"],
        includes=[],
    ),
    "skills": ToolsetDef(
        description="Inspect, package, benchmark, and reload skills.",
        tools=["skill", "reload_skills", "package_skill", "benchmark_skill"],
        includes=[],
    ),
    "media": ToolsetDef(
        description="Speech, vision, image generation, microphone capture.",
        tools=["text_to_speech", "vision_analyze", "image_generate", "listen"],
        includes=[],
    ),
    "avatar": ToolsetDef(
        description=(
            "Avatar face expressions + animation timelines. BETA — the "
            "tools register beta=True, so they only reach the agent in "
            "dev mode (JAEGER_DEV_MODE=1 / --dev) while Mochi is the "
            "animation testbed."
        ),
        tools=["set_avatar_state", "play_timeline"],
        includes=[],
    ),
    "delegate": ToolsetDef(
        description="Hand off subtasks to a fresh agent, clarify, or ask for help.",
        tools=["delegate_task", "clarify", "help_me"],
        includes=[],
    ),
    "comm": ToolsetDef(
        description="Cross-platform messaging + plugin awareness.",
        tools=["send_message", "list_plugins", "setup_plugin"],
        includes=[],
    ),
    "host_ui": ToolsetDef(
        description="Open files / URLs / apps on the host (Finder / browser).",
        tools=["open_on_host"],
        includes=[],
    ),
    "computer": ToolsetDef(
        description=(
            "macOS desktop control via cua-driver — screenshots, mouse, "
            "keyboard, scrolling. ``computer_use`` and ``computer_do`` are "
            "the high-level entry points; the rest are atomic ops."
        ),
        tools=[
            "computer_use", "computer_do", "computer_look", "computer_capture",
            "computer_windows", "computer_open", "computer_click",
            "computer_type", "computer_key", "computer_menu",
            "computer_screenshot",
            "computer_bg_apps", "computer_bg_windows", "computer_bg_move",
            "computer_bg_resize", "computer_bg_press", "computer_bg_js",
        ],
        includes=[],
    ),
    "computer_umbrella_only": ToolsetDef(
        description=(
            "Hermes-style computer use: just the two umbrellas "
            "(``computer_use`` action-dispatch + ``computer_do`` goal-dispatch)."
        ),
        tools=["computer_use", "computer_do"],
        includes=[],
    ),
    "toolset_mgmt": ToolsetDef(
        description="Load a different toolset mid-session.",
        tools=["load_toolset"],
        includes=[],
    ),

    # ── composite toolsets ─────────────────────────────────────────
    "essentials": ToolsetDef(
        description=(
            "The always-on minimum: time, math, host status, planning. "
            "Cheap deterministic tools the assistant needs constantly. "
            "Costs ~1.5K tokens in the schema."
        ),
        tools=[],
        includes=["time", "math", "host", "planning", "toolset_mgmt"],
    ),
    "default": ToolsetDef(
        description=(
            "Sensible chat-assistant default: essentials + files + web + "
            "memory + delegate. Covers the L1/L2 bench prompts."
        ),
        tools=[],
        includes=["essentials", "files", "web", "memory", "delegate", "schedule"],
    ),
    "default_consolidated": ToolsetDef(
        description=(
            "Same as ``default`` but uses the umbrella-only memory + kanban "
            "variants — Hermes-style. Smaller schema, but routing depends "
            "on the model handling the action= dispatch correctly."
        ),
        tools=[],
        includes=[
            "essentials", "files", "web", "memory_umbrella_only",
            "delegate", "schedule",
        ],
    ),
    "developer": ToolsetDef(
        description="Code-heavy workload: default + code + skills + kanban.",
        tools=[],
        includes=["default", "code", "skills", "kanban"],
    ),
    "robot": ToolsetDef(
        description=(
            "Embodied workload — what a humanoid / UAV deployment needs: "
            "essentials + files + media + computer + comm. No web by "
            "default (latency)."
        ),
        tools=[],
        includes=["essentials", "files", "media", "computer", "comm"],
    ),
    "full": ToolsetDef(
        description="Every registered tool. Big schema; use only when nothing else fits.",
        tools=[],
        includes=[
            "essentials", "files", "web", "memory", "code", "schedule",
            "kanban", "browser", "skills", "media", "delegate", "comm",
            "host_ui", "computer",
        ],
    ),
}


# ── resolution ─────────────────────────────────────────────────────


def resolve_toolsets(
    names: set[str] | frozenset[str] | list[str],
) -> set[str]:
    """Expand toolset names → the union of every tool name they contain.

    Recurses through ``includes`` with cycle detection. Unknown toolset
    names raise :class:`KeyError` — caller's responsibility to validate
    upstream (e.g. a slash command), but the agent loop catches the
    error and surfaces it as a tool result so a typo doesn't crash the
    turn.

    The special name ``"*"`` returns every tool in every registered
    toolset — convenience for ``--all-tools`` style invocations.
    """
    if "*" in names:
        names = set(JAEGER_TOOLSETS.keys())

    tools: set[str] = set()
    visited: set[str] = set()

    def _expand(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        if name not in JAEGER_TOOLSETS:
            raise KeyError(f"unknown toolset: {name!r}")
        definition = JAEGER_TOOLSETS[name]
        for t in definition.get("tools", []):
            tools.add(t)
        for inc in definition.get("includes", []):
            _expand(inc)

    for name in names:
        _expand(name)
    return tools


def list_toolsets() -> dict[str, dict[str, Any]]:
    """Return a copy of :data:`JAEGER_TOOLSETS` with the resolved tool
    list expanded for each entry — what the ``/toolsets`` slash command
    or a TUI catalogue display would show."""
    out: dict[str, dict[str, Any]] = {}
    for name, definition in JAEGER_TOOLSETS.items():
        try:
            resolved = sorted(resolve_toolsets({name}))
        except KeyError:
            resolved = []
        out[name] = {
            "description": definition.get("description", ""),
            "tools": resolved,
            "includes": list(definition.get("includes", [])),
        }
    return out


def toolset_for_tool(tool_name: str) -> str | None:
    """Reverse lookup — return the (first) atomic toolset that owns
    ``tool_name``, or ``None`` if no atomic toolset claims it. Used by
    the ``/runtime`` panel to label individual tools by category."""
    for name, definition in JAEGER_TOOLSETS.items():
        if definition.get("includes"):
            continue  # skip composites
        if tool_name in definition.get("tools", []):
            return name
    return None


__all__ = [
    "JAEGER_TOOLSETS",
    "ToolsetDef",
    "resolve_toolsets",
    "list_toolsets",
    "toolset_for_tool",
]
