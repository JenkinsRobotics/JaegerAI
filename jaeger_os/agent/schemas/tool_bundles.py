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
    in ``main.py``. Tool membership is DERIVED from
    ``skill_registry.toolset_scoping`` (CORE + TOOLSETS — the live
    visibility gate) rather than hand-maintained in parallel; only
    the bundle groupings/composites live here.

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

from jaeger_os.agent.skill_registry.toolset_scoping import (
    CORE as _SCOPING_CORE,
    TOOLSETS as _SCOPING,
)


# A *toolset definition*. ``includes`` references other toolsets by
# name; the resolver recurses (with cycle detection). ``description``
# is human-readable for ``/toolsets`` / ``/runtime`` panels.
class ToolsetDef(dict):  # type: ignore[type-arg]
    """Plain dict carrying ``description``, ``tools``, ``includes``.
    Subclassing ``dict`` keeps the literal-style definitions below
    natural to read without a frozendict / dataclass ceremony."""


# ── derivation helpers ─────────────────────────────────────────────
#
# The tool→group classification is single-sourced from
# ``toolset_scoping`` (the live visibility gate). The bundles below
# never restate a tool list the scoping map already owns — they
# compose it. Every helper validates its names at import time, so a
# rename/removal in toolset_scoping fails loudly here instead of
# leaving a stale parallel copy (the drift these two hand-maintained
# maps used to grow).


def _scoping(*toolset_names: str) -> set[str]:
    """Union of whole ``toolset_scoping.TOOLSETS`` groups."""
    missing = [n for n in toolset_names if n not in _SCOPING]
    if missing:
        raise KeyError(
            f"tool_bundles references unknown toolset_scoping groups: {missing}")
    out: set[str] = set()
    for n in toolset_names:
        out |= _SCOPING[n]
    return out


def _core(*names: str) -> set[str]:
    """Named picks from ``toolset_scoping.CORE`` (membership-checked)."""
    missing = [n for n in names if n not in _SCOPING_CORE]
    if missing:
        raise ValueError(
            f"tool_bundles names tools missing from toolset_scoping.CORE: {missing}")
    return set(names)


def _pick(toolset: str, *names: str) -> set[str]:
    """Named picks from ONE scoping group, for bundles narrower than
    the group (membership-checked so renames can't strand the pick)."""
    members = _SCOPING.get(toolset)
    if members is None:
        raise KeyError(f"tool_bundles references unknown toolset_scoping "
                       f"group: {toolset!r}")
    missing = [n for n in names if n not in members]
    if missing:
        raise ValueError(
            f"tool_bundles picks {missing} which are not in "
            f"toolset_scoping.TOOLSETS[{toolset!r}]")
    return set(names)


def _tools(*sets: set[str], exclude: set[str] = frozenset()) -> list[str]:
    """Union the pieces into the sorted ``tools`` list."""
    out: set[str] = set()
    for s in sets:
        out |= s
    return sorted(out - exclude)


# ``open_on_host`` sits in scoping's ``background`` group but is its
# own bundle atom (``host_ui``) — excluded from ``code`` below.
_HOST_UI_TOOLS = _pick("background", "open_on_host")


# ── canonical toolset map ──────────────────────────────────────────


JAEGER_TOOLSETS: dict[str, ToolsetDef] = {
    # ── atomic toolsets ────────────────────────────────────────────
    "time": ToolsetDef(
        description="Current date + time (the model's only source of truth).",
        tools=_tools(_core("get_time")),
        includes=[],
    ),
    "math": ToolsetDef(
        description="Safe arithmetic + expressions.",
        tools=_tools(_core("calculate")),
        includes=[],
    ),
    "host": ToolsetDef(
        description="Machine health, self-diagnostics, stored credentials.",
        tools=_tools(_scoping("diagnostics", "credentials")),
        includes=[],
    ),
    "files": ToolsetDef(
        description="Read / write / patch / delete / list / search the sandboxed workspace.",
        tools=_tools(_core("read_file", "write_file"), _scoping("files")),
        includes=[],
    ),
    "web": ToolsetDef(
        description="Web search, content extraction, current weather.",
        tools=_tools(_core("web_search", "web_extract"), _scoping("web")),
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
        tools=_tools(_core("memory", "recall"),
                     _scoping("memory_granular", "identity")),
        includes=[],
    ),
    "memory_umbrella_only": ToolsetDef(
        description=(
            "Hermes-style memory: ONE umbrella tool with action= dispatch. "
            "Avoids the 'umbrella vs sibling' attractor split that hurt the "
            "bench's L1 routing."
        ),
        tools=_tools(_core("memory"), _scoping("identity")),
        includes=[],
    ),
    "code": ToolsetDef(
        description="Run Python, run shell, manage the workspace venv + background processes.",
        tools=_tools(_core("execute_code"), _scoping("code", "background"),
                     exclude=_HOST_UI_TOOLS),
        includes=[],
    ),
    "schedule": ToolsetDef(
        description="Cron-style scheduling of future prompts.",
        tools=_tools(_scoping("scheduling")),
        includes=[],
    ),
    "planning": ToolsetDef(
        description="Within-session todo list + queue deep-think tasks.",
        tools=_tools(_core("todo"),
                     _pick("skills", "propose_deep_think_task",
                           "list_deep_think_queue")),
        includes=[],
    ),
    "kanban": ToolsetDef(
        description="Cross-session kanban board for durable work (individual verbs).",
        tools=_tools(_core("board_add", "board_view"), _scoping("board")),
        includes=[],
    ),
    "browser": ToolsetDef(
        description="Browser automation (navigate, click, type, scroll).",
        tools=_tools(_pick("computer_use", "browser")),
        includes=[],
    ),
    "skills": ToolsetDef(
        description=(
            "Inspect, package, benchmark, reload skills; the usage journal "
            "+ review loop; the deep-think queue."
        ),
        tools=_tools(_core("list_skills"), _scoping("skills")),
        includes=[],
    ),
    "media": ToolsetDef(
        description=(
            "Speech, vision, microphone capture; image/video generation "
            "(local + fal.ai cloud)."
        ),
        tools=_tools(_scoping("media")),
        includes=[],
    ),
    "avatar": ToolsetDef(
        description=(
            "Avatar face expressions + animation timelines. BETA — the "
            "tools register beta=True, so they only reach the agent in "
            "dev mode (JAEGER_DEV_MODE=1 / --dev) while Mochi is the "
            "animation testbed."
        ),
        tools=_tools(_scoping("avatar")),
        includes=[],
    ),
    "delegate": ToolsetDef(
        description="Hand off subtasks to a fresh agent, clarify, or ask for help.",
        tools=_tools(_core("delegate_task", "clarify", "help_me")),
        includes=[],
    ),
    "comm": ToolsetDef(
        description="Cross-platform messaging + plugin awareness.",
        tools=_tools(_scoping("plugins")),
        includes=[],
    ),
    "host_ui": ToolsetDef(
        description="Open files / URLs / apps on the host (Finder / browser).",
        tools=_tools(_HOST_UI_TOOLS),
        includes=[],
    ),
    "computer": ToolsetDef(
        description=(
            "macOS desktop control via cua-driver — screenshots, mouse, "
            "keyboard, scrolling. ``computer_use`` and ``computer_do`` are "
            "the high-level entry points; the rest are atomic ops."
        ),
        # Hand-listed on purpose: beyond the ``computer_use`` umbrella
        # pair these are SKILL-registered tools (macos_computer /
        # computer_use skills), which toolset_scoping only learns at
        # runtime via register_skill_toolset — there is no static
        # scoping group to derive from.
        tools=[
            # high-level (macos_computer skill): goal + action dispatch + look
            "computer_use", "computer_do", "computer_look",
            # atomic ops (computer_use skill)
            "computer_screenshot", "computer_read_screen", "computer_open_app",
            "computer_click", "computer_type_text", "computer_press_key",
            "computer_menu_select",
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
        tools=_tools(_core("load_tools")),
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
        # Derived: CORE plus every toolset_scoping group — so groups
        # with no bundle atom of their own (people, models, bench,
        # smart_home, …) are still covered and "every registered tool"
        # stays true as scoping grows. ``computer`` is included for the
        # skill-registered computer_* tools scoping doesn't list
        # statically.
        tools=_tools(_core(*_SCOPING_CORE), _scoping(*_SCOPING)),
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
