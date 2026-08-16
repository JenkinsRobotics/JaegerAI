from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

from jaeger_os.core.tools.tool_registry import get_tool, has_tool

from jaeger_ai.core.instance.instance import InstanceLayout
from jaeger_ai.core.mcp import service
from jaeger_ai.plugins.mcp import client


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"HTTP MCP fixture exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError("HTTP MCP fixture did not start")


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


def test_streamable_http_reload_inventory_dispatch_and_secret_persistence(tmp_path):
    root = tmp_path / "instance"
    root.mkdir()
    layout = InstanceLayout(root)
    layout.ensure_dirs()
    port = _unused_port()
    server = tmp_path / "http_mcp.py"
    server.write_text(
        "import os\n"
        "from mcp.server.fastmcp import FastMCP\n"
        f"server = FastMCP('http-fixture', host='127.0.0.1', port={port}, stateless_http=True)\n"
        "@server.tool()\n"
        "def echo(value: str) -> str:\n"
        "    return f'http:{value}'\n"
        "server.run(transport='streamable-http')\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(server)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_port(port, process)
        service.configure_server(layout, "remote", {
            "url": f"http://127.0.0.1:{port}/mcp",
            "headers": {"Authorization": "Bearer never-in-json"},
        })
        assert "never-in-json" not in layout.mcp_config_path.read_text()

        first = service.reload_tools(layout)
        assert first["unavailable_servers"] == []
        assert first["tools"][0]["name"] == "mcp__remote__echo"
        assert service.list_servers(layout)["servers"][0]["transport"] == "http"
        result = get_tool("mcp__remote__echo").dispatch({"value": "first"})
        assert result["text"] == "http:first"

        client.shutdown_global()
        second = service.reload_tools(layout)
        assert second["unavailable_servers"] == []
        result = get_tool("mcp__remote__echo").dispatch({"value": "after-restart"})
        assert result["text"] == "http:after-restart"

        saved = json.loads(layout.mcp_config_path.read_text())["servers"][0]
        assert saved["headers"]["Authorization"] == {
            "secret_ref": "mcp.remote.header.Authorization",
        }
    finally:
        client.shutdown_global()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
