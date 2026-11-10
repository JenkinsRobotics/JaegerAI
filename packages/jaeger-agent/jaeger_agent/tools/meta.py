"""Search, inspect and load tools through Jaeger's existing registry and executor."""
from __future__ import annotations
from typing import Any
from jaeger_os.core.tools.tool_registry import register_tool_from_function
from jaeger_agent.skill_registry import tool_discovery as discovery


@register_tool_from_function(permission_tier='READ_ONLY', side_effect='read')
def describe_tool(name: str) -> dict[str, Any]:
    """Inspect a permitted tool's schema, availability and permission metadata before loading it.
    An unspecified permission tier is unknown; it never implies approval to execute.
    """
    tool = next((t for t in discovery.catalog() if t.name == name.strip()), None)
    if tool is None:
        return {'ok': False, 'error': 'Unknown or unavailable tool in this agent’s catalog'}
    fn = discovery.schema(tool)['function']
    return {'ok': True, **discovery.row(tool), 'name': tool.name,
            'description': fn.get('description', ''), 'parameters': fn.get('parameters', {}),
            'permission_tier': getattr(tool, 'permission_tier', '') or 'UNKNOWN',
            'side_effect': getattr(tool, 'side_effect', '') or 'unknown',
            'requires_env': list(getattr(tool, 'requires_env', ()) or ()),
            'max_result_chars': int(getattr(tool, 'max_result_chars', 0) or 0),
            'examples': list(getattr(tool, 'examples', ()) or ()),
            'interactive': bool(getattr(tool, 'interactive', False)),
            'dangerous': bool(getattr(tool, 'dangerous', False)),
            'beta': bool(getattr(tool, 'beta', False))}


@register_tool_from_function(permission_tier='READ_ONLY', side_effect='write')
def load_tools(name: str = '', tools: list[str] | None = None) -> dict[str, Any]:
    """Load exact tool names returned by list_tools using tools=[...], or a named toolset.
    Tools become visible on the next model step for this agent only. Loading grants no
    permission to execute. Missing prerequisites are reported without installing anything.
    Call with no arguments to see permitted groups. At most 20 exact tools per call.
    """
    from jaeger_agent.skill_registry.tool_selection import current_selection
    from jaeger_agent.skill_registry.toolset_scoping import (
        active_toolset_names, enable_toolset, is_untrusted_content,
    )
    if is_untrusted_content():
        return {'ok': False, 'error': 'Tool loading is unavailable for untrusted content'}
    catalog = discovery.catalog()
    by_name = {t.name: t for t in catalog}
    clean = name.strip()
    exact = list(dict.fromkeys(tools or ([] if clean not in by_name else [clean])))
    if len(exact) > 20:
        return {'ok': False, 'error': 'Load at most 20 exact tools at a time'}
    if exact:
        state = current_selection()
        if state is None:
            return {'ok': False, 'error': 'Exact tools must be loaded within an agent session'}
        if any(n not in by_name for n in exact):
            return {'ok': False, 'error': 'Requested tool is not in this agent’s catalog'}
        unavailable = [discovery.row(by_name[n]) for n in exact if not discovery.availability(by_name[n])[0]]
        if unavailable:
            return {'ok': False, 'error': 'Resolve tool prerequisites before loading', 'unavailable': unavailable}
        state.names.update(exact)
        state.reasons.update({n: 'Explicitly loaded' for n in exact})
        return {'ok': True, 'loaded': exact, 'tools': [describe_tool(n) for n in exact]}
    available = discovery.groups(catalog)
    clean = clean.lower()
    if clean in available:
        members = [t for t in catalog if discovery.group(t) == clean]
        ready = [t for t in members if discovery.availability(t)[0]]
        if not ready:
            return {'ok': False, 'error': 'Group has no available tools',
                    'unavailable': [discovery.row(t) for t in members]}
        state = current_selection()
        enabled = enable_toolset(clean)
        if state is not None:
            state.names.update(t.name for t in ready)
            state.reasons.update({t.name: 'Loaded group: ' + clean for t in ready})
            enabled = True
        if enabled:
            return {'ok': True, 'loaded': clean, 'active': sorted(active_toolset_names()),
                    'tools': [t.name for t in ready],
                    'unavailable': [discovery.row(t) for t in members if t not in ready]}
    return {'ok': False, 'error': 'Choose a permitted tool or group', 'available': available}


@register_tool_from_function(permission_tier='READ_ONLY', side_effect='read')
def list_tools(query: str = '', limit: int = 5, source: str = '') -> dict[str, Any]:
    """Find tools by task, exact name or service, e.g. 'search inbox'. Results are ranked
    and bounded, with availability and loadable names. Use load_tools(tools=[name]) next.
    Source optionally limits results to a group/server. Search does not execute tools.
    """
    limit = max(1, min(int(limit), 20))
    catalog = discovery.catalog()
    candidates = [t for t in catalog if not source or discovery.group(t) == source]
    matches = discovery.ranked(candidates, query[:1000], limit) if query.strip() else candidates[:limit]
    rows = [discovery.row(t) for t in matches]
    out = {'ok': True, 'count': len(rows), 'catalog_count': len(candidates), 'tools': rows,
           'note': 'Load exact tools with load_tools(tools=[name]), or load_tools(name=<toolset>)'}
    if not rows:
        out['toolsets'] = discovery.groups(catalog)
    return out


__all__ = ['describe_tool', 'load_tools', 'list_tools']
