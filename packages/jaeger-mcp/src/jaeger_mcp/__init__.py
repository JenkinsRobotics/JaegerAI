"""jaeger-mcp — Synthesized MCP policy, schema cache, byte budgets, connection pool, Seatbelt sandbox, prompts & roots."""

from .budget import (
    MAX_TOOL_SCHEMA_BYTES,
    MAX_TOTAL_SCHEMA_BYTES,
    MCPConnectionPool,
    PooledConnection,
    SchemaBudgetReport,
    enforce_mcp_schema_budget,
)
from .policy import ALLOWED_TOOL_POLICY_KEYS, MASK, MCPToolPolicy, SECRET_KEY_RE, agent_tool_name, redact_secrets
from .protocol import MCPPromptSpec, ReconnectPolicy, build_roots_payload
from .sandbox import build_mcp_seatbelt_profile, wrap_stdio_with_seatbelt
from .schema_cache import CachedToolEntry, MCPSchemaCache

__all__ = [
    "ALLOWED_TOOL_POLICY_KEYS",
    "CachedToolEntry",
    "MASK",
    "MAX_TOOL_SCHEMA_BYTES",
    "MAX_TOTAL_SCHEMA_BYTES",
    "MCPConnectionPool",
    "MCPPromptSpec",
    "MCPSchemaCache",
    "MCPToolPolicy",
    "PooledConnection",
    "ReconnectPolicy",
    "SECRET_KEY_RE",
    "SchemaBudgetReport",
    "agent_tool_name",
    "build_mcp_seatbelt_profile",
    "build_roots_payload",
    "enforce_mcp_schema_budget",
    "redact_secrets",
    "wrap_stdio_with_seatbelt",
]
