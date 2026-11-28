"""jaeger-mcp — Synthesized MCP policy, schema cache, byte budgets, connection pool, Seatbelt sandbox, prompts & roots."""

from .budget import (
    MAX_TOOL_SCHEMA_BYTES,
    MAX_TOTAL_SCHEMA_BYTES,
    MCPConnectionPool,
    PooledConnection,
    SchemaBudgetReport,
    enforce_mcp_schema_budget,
)
from .client import (
    LiveMCPManager,
    MAX_MCP_IMAGE_BYTES,
    MCPServerConfig,
    MCPServerHealth,
    extract_mcp_content,
    load_mcp_server_configs,
    remove_mcp_server_config,
    save_mcp_server_config,
)
from .policy import ALLOWED_TOOL_POLICY_KEYS, MASK, MCPToolPolicy, SECRET_KEY_RE, agent_tool_name, redact_secrets
from .presets import BUILTIN_MCP_PRESETS, MCPServerPreset, build_preset_config, list_mcp_presets
from .protocol import MCPPromptSpec, ReconnectPolicy, build_roots_payload
from .sandbox import build_mcp_seatbelt_profile, wrap_stdio_with_seatbelt
from .schema_cache import CachedToolEntry, MCPSchemaCache

__all__ = [
    "ALLOWED_TOOL_POLICY_KEYS",
    "BUILTIN_MCP_PRESETS",
    "CachedToolEntry",
    "LiveMCPManager",
    "MASK",
    "MAX_MCP_IMAGE_BYTES",
    "MAX_TOOL_SCHEMA_BYTES",
    "MAX_TOTAL_SCHEMA_BYTES",
    "MCPConnectionPool",
    "MCPPromptSpec",
    "MCPSchemaCache",
    "MCPServerConfig",
    "MCPServerHealth",
    "MCPServerPreset",
    "MCPToolPolicy",
    "PooledConnection",
    "ReconnectPolicy",
    "SECRET_KEY_RE",
    "SchemaBudgetReport",
    "agent_tool_name",
    "build_mcp_seatbelt_profile",
    "build_preset_config",
    "build_roots_payload",
    "enforce_mcp_schema_budget",
    "extract_mcp_content",
    "list_mcp_presets",
    "load_mcp_server_configs",
    "redact_secrets",
    "remove_mcp_server_config",
    "save_mcp_server_config",
    "wrap_stdio_with_seatbelt",
]
