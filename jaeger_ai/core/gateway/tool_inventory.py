"""Read-only projection of already-loaded canonical tool/MCP owners.

No module discovery, tool check_fn execution, connections or credential setup.
Inventory is not an execution grant or proof that a dependency is healthy.
"""
from __future__ import annotations
import sys
from typing import Any
from jaeger_ai.core.redaction import redact_text


def collect(query: str = '') -> dict[str, Any]:
    from jaeger_os.core.tools.tool_registry import get_tools
    module = sys.modules.get('jaeger_ai.plugins.mcp.client')
    mcp = module.runtime_inventory() if module is not None else {'initialized': False, 'servers': [], 'tools': []}
    links = {tool['agent_name']: tool for tool in mcp['tools']}
    rows = []
    for tool in get_tools():
        link = links.get(tool.name)
        # MCP metadata is redacted by its owner using loaded known secrets.
        description = link['description'] if link else redact_text(tool.description)[:1000]
        row = {'name': link['display_name'] if link else redact_text(tool.name), 'description': description,
               'toolset': redact_text(tool.toolset), 'source': 'mcp' if link else 'gateway',
               'server': link['server'] if link else None,
               'side_effect': tool.side_effect or 'unclassified', 'permission_tier': tool.permission_tier or 'unspecified',
               'beta': bool(tool.beta), 'dangerous': bool(tool.dangerous), 'availability': 'not_probed'}
        if not query or query.casefold() in ' '.join(str(row[k] or '') for k in ('name', 'description', 'toolset', 'server')).casefold():
            rows.append(row)
    rows.sort(key=lambda row: (row['source'], row['server'] or '', row['name']))
    return {'tools': rows, 'count': len(rows), 'servers': mcp['servers'], 'mcp_initialized': mcp['initialized'],
            'scope': 'already_registered_only', 'execution_authorized': False}
