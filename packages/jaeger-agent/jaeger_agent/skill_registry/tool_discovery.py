"""Discovery views over the canonical registry, filtered by current agent authority."""
from __future__ import annotations

from typing import Any
from .tool_selection import current_selection, tool_permitted
from .toolset_scoping import all_toolsets, tool_group, tool_visible


def catalog() -> list[Any]:
    from jaeger_os.core.tools.tool_registry import get_tools
    from jaeger_os.core.tools.tool_schema import dev_mode_enabled
    state = current_selection()
    tools = state.catalog if state is not None and state.catalog is not None else get_tools()
    return sorted((t for t in tools if tool_permitted(t.name)
                   and (not getattr(t, 'beta', False) or dev_mode_enabled())), key=lambda t: t.name)


def availability(tool: Any) -> tuple[bool, str]:
    import os
    missing = [key for key in getattr(tool, 'requires_env', ()) if not os.environ.get(key)]
    if missing:
        return False, 'Needs configuration: ' + ', '.join(missing)
    try:
        ready = bool(tool.is_available()) if hasattr(tool, 'is_available') else True
    except Exception:
        return False, 'Availability check failed'
    return (True, '') if ready else (False, 'Runtime prerequisite is unavailable')


def group(tool: Any) -> str:
    return tool_group(tool.name) or getattr(tool, 'toolset', '') or ''


def groups(tools: list[Any]) -> dict[str, str]:
    summaries = all_toolsets()
    return {g: summaries.get(g, g) for g in sorted({group(t) for t in tools}) if g and g != 'core'}


def schema(tool: Any) -> dict[str, Any]:
    if hasattr(tool, 'to_openai_schema'):
        return tool.to_openai_schema()
    return {'type': 'function', 'function': {'name': tool.name,
            'description': tool.description, 'parameters': {}}}


def row(tool: Any) -> dict[str, Any]:
    ready, reason = availability(tool)
    g = group(tool)
    state = current_selection()
    selected = ready and tool_visible(tool.name)
    why = (state.reasons.get(tool.name) if state else None) or (
        'Matched this task' if state and tool.name in state.inferred else
        'Core tool' if g == 'core' else 'Loaded group' if state and g in state.groups
        else 'Available by default')
    return {'tool': tool.name, 'toolset': g, 'source': g or 'registered',
            'does': ' '.join((tool.description or '').split())[:160],
            'available': ready, 'unavailable_reason': reason, 'selected': selected,
            'selection_reason': why if selected else 'Load this tool when needed'}


def ranked(tools: list[Any], query: str, limit: int) -> list[Any]:
    from .tool_search import CatalogEntry, _entry_search_text, _tokenize, search_catalog
    by_name = {t.name: t for t in tools}
    entries = []
    for tool in tools:
        if tool.name in {"list_tools", "describe_tool", "load_tools"} and query.strip() != tool.name:
            continue
        td = schema(tool)
        g = group(tool)
        entries.append(CatalogEntry(tool.name, tool.description, td, 'registered', g,
                                   _tokenize(_entry_search_text(td, g))))
    return [by_name[e.name] for e in search_catalog(entries, query, limit)]
