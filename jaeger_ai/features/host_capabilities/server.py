"""Native FastMCP host capability server for Jaeger AI.

Exposes identity-scoped, audited host tools to agent runtimes (Hermes, OpenClaw, Jaeger)
via FastMCP over stdio.
"""

from __future__ import annotations

import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

from .camera_tools import (
    camera_listen,
    camera_ptz,
    camera_snapshot,
    camera_status,
)
from .grants import get_current_identity
from .mac_tools import (
    calendar_create,
    calendar_list,
    notes_create,
    notes_list,
    notes_read,
    reminders_create,
    reminders_list,
    shortcuts_list,
    shortcuts_run,
)
from .memory_tools import (
    memory_add,
    memory_context,
    memory_query,
    memory_status,
)
from .system_tools import (
    capabilities_inspect,
    host_environment,
    service_restart,
    service_status,
)
from .workspace_tools import (
    git_diff,
    git_status,
    workspace_delete,
    workspace_list,
    workspace_mkdir,
    workspace_move,
    workspace_read,
    workspace_write,
)

identity = get_current_identity()
# Compatible with both 'ares-host-{identity}' and 'jaeger-host-{identity}'
mcp = FastMCP(f"ares-host-{identity}")

# 1. System & Identity Tools
mcp.tool()(capabilities_inspect)
mcp.tool()(host_environment)
mcp.tool()(service_status)
mcp.tool()(service_restart)

# 2. Workspace File & Git Tools
mcp.tool()(workspace_list)
mcp.tool()(workspace_read)
mcp.tool()(workspace_write)
mcp.tool()(workspace_mkdir)
mcp.tool()(workspace_move)
mcp.tool()(workspace_delete)
mcp.tool()(git_status)
mcp.tool()(git_diff)

# 3. macOS Integration Tools
mcp.tool()(calendar_list)
mcp.tool()(calendar_create)
mcp.tool()(notes_list)
mcp.tool()(notes_read)
mcp.tool()(notes_create)
mcp.tool()(reminders_list)
mcp.tool()(reminders_create)
mcp.tool()(shortcuts_list)
mcp.tool()(shortcuts_run)

# 4. Camera Tools
mcp.tool()(camera_status)
mcp.tool()(camera_snapshot)
mcp.tool()(camera_listen)
mcp.tool()(camera_ptz)

# 5. Shared Memory Tools
mcp.tool()(memory_status)
mcp.tool()(memory_query)
mcp.tool()(memory_context)
mcp.tool()(memory_add)


def main() -> None:
    """Run the FastMCP server on stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
