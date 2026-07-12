"""Meta-tools — the model's introspection surface for its own toolbox.

When the lean tool surface is on (opt-in via ``JAEGER_TOOLSET_SCOPING=1``;
default OFF in 0.1.0), the model sees a CORE set + a catalog of every
other toolset. Two meta-tools make that pattern workable:

  - :func:`describe_tool` — peek at any registered tool's schema
    without changing the active set. Cheap.
  - :func:`load_tools` — widen the active set to include a whole
    category for the rest of the session.

Both also exist when the lean surface is OFF — describe_tool stays
useful as introspection, load_tools is a no-op-by-config but won't
break.

Why a separate ``meta.py`` instead of folding into ``_common.py``:
the meta-tools touch the agent's tool *registry* rather than the
filesystem or the model — distinct enough that growing this file
(future: ``introspect_message_count``, ``trace_last_turn``) makes
sense in one place.

Both tools are registered at module-import time via
``register_tool_from_function`` so they're available before any
agent is built — main.py used to wrap them again inside the agent
construction closure, which created a drift risk (two copies of the
same docstring + dispatch shape).
"""

from __future__ import annotations

from typing import Any

from jaeger_os.core.tools.tool_registry import register_tool_from_function


@register_tool_from_function
def describe_tool(name: str) -> dict[str, Any]:
    """Show the FULL schema + registry metadata for one tool — even
    one that's not currently in the agent's visible toolset. Use this
    when you see a tool name in the catalog and want to know exactly
    what arguments it takes (or what its permission tier / availability
    constraints are) BEFORE deciding to use it.

    Returns:
      * ``name`` / ``description`` / ``parameters`` — the same schema
        the model would see in its tools list
      * ``toolset`` — the category the tool belongs to (``"core"``,
        ``"files"``, ``"computer_use"``, etc.) so you know which
        ``load_tools`` call would bring its siblings in
      * ``permission_tier`` — ``READ_ONLY`` / ``WRITE_LOCAL`` /
        ``EXTERNAL_EFFECT`` / ``HARDWARE`` / ``PRIVILEGED``. Tells you
        whether calling it will need user confirmation.
      * ``side_effect`` — coarser hint: ``read`` / ``write`` /
        ``external`` / ``hardware``.
      * ``available`` — False when a runtime precondition fails
        (missing deps, missing env var). The tool is still registered
        but calling it would fail; you'd need to install / configure
        first.
      * ``requires_env`` — env-var names the tool needs at runtime
        (e.g. ``["OPENAI_API_KEY"]``).
      * ``max_result_chars`` — per-tool result size cap (0 = use the
        global default).
      * ``examples`` — short example call shapes, when authored.

    ``{ok: False, error}`` for an unknown name.
    """
    from jaeger_os.core.tools.tool_registry import get_tool, has_tool
    from jaeger_ai.agent.skill_registry.toolset_scoping import (
        CORE, TOOLSETS, _SKILL_TOOLSETS,
    )

    clean = (name or "").strip()
    if not clean:
        return {"ok": False, "error": "empty tool name"}
    if not has_tool(clean):
        return {"ok": False, "error": f"unknown tool {name!r}"}
    tool = get_tool(clean)
    schema: dict[str, Any] = (
        tool.to_openai_schema() if hasattr(tool, "to_openai_schema") else {}
    )
    function = schema.get("function", {}) if isinstance(schema, dict) else {}

    # Toolset resolution: prefer the explicit ``ToolDef.toolset`` field
    # when populated; fall back to membership scan of the static maps
    # so unmigrated tools still report something meaningful.
    declared = getattr(tool, "toolset", "") or ""
    if not declared:
        if clean in CORE:
            declared = "core"
        else:
            for ts_name, members in TOOLSETS.items():
                if clean in members:
                    declared = ts_name
                    break
            else:
                for ts_name, members in _SKILL_TOOLSETS.items():
                    if clean in members:
                        declared = f"skill:{ts_name}"
                        break

    return {
        "ok": True,
        "name": function.get("name") or tool.name,
        "description": function.get("description", ""),
        "parameters": function.get("parameters", {}),
        "toolset": declared or "(unclassified)",
        "permission_tier": getattr(tool, "permission_tier", "") or "READ_ONLY",
        "side_effect": getattr(tool, "side_effect", "") or "(unclassified)",
        "available": tool.is_available() if hasattr(tool, "is_available")
                     else True,
        "requires_env": list(getattr(tool, "requires_env", ()) or ()),
        "max_result_chars": int(getattr(tool, "max_result_chars", 0) or 0),
        "examples": list(getattr(tool, "examples", ()) or ()),
        "interactive": bool(getattr(tool, "interactive", False)),
        "dangerous": bool(getattr(tool, "dangerous", False)),
        "beta": bool(getattr(tool, "beta", False)),
    }


@register_tool_from_function
def load_tools(name: str = "") -> dict[str, Any]:
    """Make a group of extra tools visible. You start each turn with
    a small CORE toolset; everything else is grouped — built-in
    classes (``files``, ``code``, ``media``, …) and skills (each skill
    is its own toolset of curated tools).

    Call this the MOMENT a task needs a capability you don't see a
    tool for — BEFORE concluding you can't do it. The new tools appear
    on your very next step. Call with no name (or an unknown one) to
    get the catalog of every toolset and what it holds. Returns the
    toolsets now active.

    No-op when ``JAEGER_TOOLSET_SCOPING`` is off (the 0.1.0 default) —
    every tool is already visible. The active-set tracking still works
    so this is harmless to call regardless of the scoping mode.
    """
    from jaeger_ai.agent.skill_registry.toolset_scoping import (
        active_toolset_names, all_toolsets, enable_toolset,
    )
    clean = (name or "").strip().lower()
    if enable_toolset(clean):
        return {"ok": True, "loaded": clean,
                "active": sorted(active_toolset_names())}
    return {
        "ok": False,
        "error": (f"unknown toolset {name!r}" if clean
                  else "give a toolset name — catalog below"),
        "available": all_toolsets(),
    }


@register_tool_from_function
def list_tools(query: str = "") -> dict[str, Any]:
    """Find a SPECIFIC tool by keyword when the exact tool a task needs isn't in
    your current view — e.g. ``list_tools("weather")`` → ``get_weather`` in the
    ``web`` toolset; then ``load_tools("web")`` to use it. It returns matching
    tool names + their toolset, NOT a description of your capabilities — for
    "what can you do / help" use ``help_me``, not this. When every tool is
    already visible you rarely need it. Optional ``query`` filters by substring."""
    from jaeger_os.core.tools.tool_registry import get_tools
    from jaeger_ai.agent.skill_registry.toolset_scoping import CORE, TOOLSETS
    where: dict[str, str] = {}
    for ts, tools in TOOLSETS.items():
        for t in tools:
            where[t] = ts
    q = (query or "").strip().lower()
    rows = []
    for t in sorted(get_tools(), key=lambda x: x.name):
        desc = " ".join((t.description or "").split())[:80]
        if q and q not in t.name.lower() and q not in desc.lower():
            continue
        loc = "CORE" if t.name in CORE else where.get(t.name, "other")
        rows.append({"tool": t.name, "toolset": loc, "does": desc})
    return {"ok": True, "count": len(rows), "tools": rows,
            "note": "not-CORE tools: load their toolset with load_tools(<toolset>)"}


__all__ = ["describe_tool", "load_tools", "list_tools"]
