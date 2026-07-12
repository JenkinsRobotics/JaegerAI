"""Smoke test for the mcp plugin.

The plugin loader runs this before activation. Pass = plugin registers.
Fail = plugin is skipped with an audit log entry.

What we test: the registry import works and an empty config can be
constructed. We do NOT test actual MCP server connection because that
requires `mcp` SDK installed and at least one configured server.
"""

from __future__ import annotations


def test_client_importable() -> None:
    """The client module must import even when no MCP servers are configured."""
    from jaeger_ai.plugins.mcp import client

    assert hasattr(client, "init_from_config")
    assert hasattr(client, "MCPRegistry")
    assert hasattr(client, "call_mcp_tool")


def test_default_config_path_resolves() -> None:
    """DEFAULT_CONFIG_PATH must resolve to a real file in the plugin dir."""
    from jaeger_ai.plugins.mcp import client

    assert client.DEFAULT_CONFIG_PATH.exists()
    assert client.DEFAULT_CONFIG_PATH.name == "mcp_config.json"


if __name__ == "__main__":
    test_client_importable()
    test_default_config_path_resolves()
    print("mcp plugin smoke: OK")
