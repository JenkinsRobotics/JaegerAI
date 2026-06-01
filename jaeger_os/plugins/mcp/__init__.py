"""MCP (Model Context Protocol) plugin.

Bridges the agent to external MCP server processes. Each registered MCP
server's advertised tool schema becomes a pydantic-ai Tool dynamically.

Entry point: `client.init_from_config()` returns an MCPRegistry whose
`list_tools()` provides the specs `jaeger_os.main._build_mcp_tools`
wraps into Tool objects.
"""

from __future__ import annotations

from . import client

__all__ = ["client"]
