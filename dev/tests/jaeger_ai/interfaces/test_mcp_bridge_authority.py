"""Phase 1 / workstream 1: the MCP surface cannot bypass jaegerd authority.

The live bridge exposes BRIDGE_COMMANDS (save_config, save_identity,
set_credential, install_skill, configure_mcp_server, create_schedule,
run_update, ...) that write authoritative state directly, outside the Gateway
task path and PolicyKernel. An MCP caller is an outside helper (Claude Code,
Cursor, Hermes, OpenClaw, Roundtable members). These tests prove that no MCP
tool reaches ``bridge.command`` and that ``bridge_query`` only serves an
explicit read-only allowlist.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from jaeger_ai.interfaces import mcp_server
from jaeger_ai.interfaces.bridge import BRIDGE_COMMANDS, BRIDGE_QUERIES


class _RecordingBridge:
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict]] = []
        self.queries: list[str] = []

    def health(self):
        return {"ok": True}

    def query(self, what, args=None):
        self.queries.append(what)
        if what == "list_tools":
            return {"tools": []}
        return {"ok": True, "what": what}

    def command(self, cmd, args=None):  # pragma: no cover - must never run
        self.commands.append((cmd, dict(args or {})))
        return {"ok": True}

    def turn(self, message, session="mcp", **kwargs):
        return {"text": "ok"}

    def control(self, *args, **kwargs):
        return {"ok": True}


def _server(bridge):
    return mcp_server.build_server(None, "jaeger-test", "gemma", bridge=bridge)


def _call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


def test_bridge_command_tool_is_not_registered():
    names = {t.name for t in asyncio.run(_server(_RecordingBridge()).list_tools())}
    assert "bridge_command" not in names
    assert not any("command" in n for n in names), names


@pytest.mark.parametrize("cmd", sorted(BRIDGE_COMMANDS))
def test_no_mcp_tool_can_reach_any_bridge_command(cmd):
    """Drive every registered MCP tool with the command name as payload;
    the bridge's command channel must never be invoked."""
    bridge = _RecordingBridge()
    server = _server(bridge)
    payload = json.dumps({"command": cmd, "cmd": cmd})
    for tool in asyncio.run(server.list_tools()):
        if tool.name in {"chat", "finance_summary", "finance_audit"}:
            continue  # chat routes to bridge.turn (Gateway path); finance is offline here
        props = (tool.inputSchema or {}).get("properties") or {}
        args = {}
        for key in props:
            args[key] = cmd if key in {"what", "command"} else payload if key.endswith("json") else ""
        with pytest.raises(Exception) if tool.name == "bridge_query" else _nullcontext():
            _call(server, tool.name, args)
    assert bridge.commands == []


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("what", [
    "hardware_bench_start", "hardware_bench", "system_utility", "check_update",
    "first_boot", "config", "permissions", "list_credentials", "load_session",
    "list_sessions", "search_sessions", "background_messages", "save_config",
    "set_credential", "", "IDENTITY",
])
def test_bridge_query_refuses_non_allowlisted(what):
    bridge = _RecordingBridge()
    server = _server(bridge)
    with pytest.raises(Exception, match="not available over MCP"):
        _call(server, "bridge_query", {"what": what, "args_json": "{}"})
    assert bridge.queries == []
    assert bridge.commands == []


def test_bridge_query_allowlisted_read_reaches_bridge():
    bridge = _RecordingBridge()
    _call(_server(bridge), "bridge_query", {"what": "list_tools", "args_json": "{}"})
    assert bridge.queries[-1] == "list_tools"


def test_allowlist_is_a_subset_of_real_queries_and_excludes_side_effects():
    allow = mcp_server.MCP_READ_ONLY_BRIDGE_QUERIES
    assert allow <= set(BRIDGE_QUERIES)
    assert not allow & set(BRIDGE_COMMANDS)
    for side_effect in ("hardware_bench_start", "hardware_bench", "system_utility"):
        assert side_effect not in allow


def test_mcp_module_never_calls_bridge_command():
    """Static tripwire: no code path in the MCP server forwards to the bridge's
    command channel (the PolicyKernel bypass)."""
    src = inspect.getsource(mcp_server)
    assert ".command(" not in src
