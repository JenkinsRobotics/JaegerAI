from __future__ import annotations

import json
import sys

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.mcp import service
from jaeger_ai.plugins.mcp import client
from jaeger_os.core.tools.tool_registry import get_tool, has_tool


def test_configure_reload_inventory_dispatch_and_restart(tmp_path, monkeypatch):
    root = tmp_path / "instance"
    root.mkdir()
    layout = InstanceLayout(root)
    layout.ensure_dirs()
    server = tmp_path / "echo_mcp.py"
    server.write_text(
        "from mcp.server.fastmcp import FastMCP\n"
        "server = FastMCP('lifecycle-fixture')\n"
        "@server.tool()\n"
        "def echo(value: str) -> str:\n"
        "    return f'echo:{value}'\n"
        "@server.tool()\n"
        "def environment(name: str) -> str:\n"
        "    import os\n"
        "    return os.environ.get(name, '')\n"
        "server.run()\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("UNRELATED_SECRET_DO_NOT_INHERIT", "parent-secret")
    try:
        service.configure_server(layout, "fixture", {
            "command": sys.executable, "args": [str(server)], "enabled": True,
            "env": {"FIXTURE_TOKEN": "never-in-json"},
        })
        assert "never-in-json" not in layout.mcp_config_path.read_text()

        first = service.reload_tools(layout)
        assert first["reloaded"] is True
        assert first["unavailable_servers"] == []
        assert first["tools"][0]["name"] == "mcp__fixture__echo"
        assert has_tool("mcp__fixture__echo")
        result = get_tool("mcp__fixture__echo").dispatch({"value": "first"})
        assert result["text"] == "echo:first"
        configured = get_tool("mcp__fixture__environment").dispatch({"name": "FIXTURE_TOKEN"})
        unrelated = get_tool("mcp__fixture__environment").dispatch({
            "name": "UNRELATED_SECRET_DO_NOT_INHERIT",
        })
        assert configured["text"] == "never-in-json"
        assert unrelated["text"] == ""

        client.shutdown_global()
        assert not has_tool("mcp__fixture__echo")

        second = service.reload_tools(layout)
        assert second["unavailable_servers"] == []
        result = get_tool("mcp__fixture__echo").dispatch({"value": "after-restart"})
        assert result["text"] == "echo:after-restart"

        saved = json.loads(layout.mcp_config_path.read_text())
        assert saved["servers"][0]["env"]["FIXTURE_TOKEN"] == {
            "secret_ref": "mcp.fixture.FIXTURE_TOKEN",
        }
    finally:
        client.shutdown_global()
