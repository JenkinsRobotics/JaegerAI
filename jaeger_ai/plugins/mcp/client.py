"""MCP (Model Context Protocol) bridge — opt-in extension.

Goal: keep our fast in-process tools as the default path, and add MCP servers
as opt-in extended capability. This module owns the async-to-sync bridge so
the rest of the agent can stay synchronous.

Architecture:
- A persistent asyncio event loop runs in a daemon thread
- Each configured MCP server gets an MCPClient that holds an open stdio session
- Sync calls are submitted as coroutines and awaited via run_coroutine_threadsafe
- Tools are registered globally with names like "mcp:<server>/<tool>"

This module is only imported when --with-mcp is set; default agent paths
pay zero cost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Quiet down the mcp SDK's own logging unless something goes wrong.
logging.getLogger("mcp").setLevel(logging.WARNING)


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "mcp_config.json"


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPToolSpec:
    qualified_name: str          # "mcp:web/fetch"
    server_name: str             # "web"
    tool_name: str               # "fetch"
    description: str
    input_schema: dict[str, Any]


class _MCPClient:
    """One MCP server connection. The session stays open for the process lifetime."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: Any = None
        self._exit_stack: Any = None

    async def connect(self) -> list[Any]:
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
        )
        self._exit_stack = AsyncExitStack()
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        self._session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        listing = await self._session.list_tools()
        return list(listing.tools)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return await self._session.call_tool(tool_name, arguments)

    async def close(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass


class MCPRegistry:
    """Holds clients, runs the async loop, exposes a sync API."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True, name="mcp-loop")
        self._loop_thread.start()
        self._clients: dict[str, _MCPClient] = {}
        self._tools: dict[str, MCPToolSpec] = {}

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Any, timeout: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def add_server(self, config: MCPServerConfig, *, connect_timeout: float = 20.0) -> list[MCPToolSpec]:
        client = _MCPClient(config)
        started = time.perf_counter()
        tools = self._submit(client.connect(), timeout=connect_timeout)
        elapsed = time.perf_counter() - started
        specs: list[MCPToolSpec] = []
        for tool in tools:
            qualified = f"mcp:{config.name}/{tool.name}"
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
            spec = MCPToolSpec(
                qualified_name=qualified,
                server_name=config.name,
                tool_name=tool.name,
                description=tool.description or "",
                input_schema=schema if isinstance(schema, dict) else {},
            )
            self._tools[qualified] = spec
            specs.append(spec)
        self._clients[config.name] = client
        print(f"[mcp] connected to '{config.name}' in {elapsed:.2f}s — {len(specs)} tool(s)", flush=True)
        return specs

    def call(self, qualified_name: str, arguments: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
        spec = self._tools.get(qualified_name)
        if spec is None:
            raise ValueError(f"unknown MCP tool: {qualified_name}")
        client = self._clients[spec.server_name]
        result = self._submit(client.call(spec.tool_name, arguments), timeout=timeout)
        return _result_to_dict(result)

    def list_tools(self) -> list[MCPToolSpec]:
        return list(self._tools.values())

    def has_tool(self, qualified_name: str) -> bool:
        return qualified_name in self._tools

    def shutdown(self) -> None:
        for client in self._clients.values():
            try:
                self._submit(client.close(), timeout=5.0)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=5.0)


def _result_to_dict(result: Any) -> dict[str, Any]:
    """Flatten MCP CallToolResult into plain JSON-serializable dict."""
    out: dict[str, Any] = {"isError": bool(getattr(result, "isError", False))}
    content_items: list[dict[str, Any]] = []
    for item in getattr(result, "content", []) or []:
        kind = getattr(item, "type", None)
        if kind == "text" or hasattr(item, "text"):
            content_items.append({"type": "text", "text": getattr(item, "text", "")})
        else:
            content_items.append({"type": kind or "unknown"})
    out["content"] = content_items
    # Convenience: concatenated text for the common case
    texts = [c["text"] for c in content_items if c.get("type") == "text"]
    if texts:
        out["text"] = "\n".join(texts)
    return out


# Module-level singleton, populated by init_from_config()
_GLOBAL_REGISTRY: MCPRegistry | None = None


def init_from_config(config_path: Path | None = None) -> MCPRegistry:
    """Initialize the global MCP registry from a JSON config file."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is not None:
        return _GLOBAL_REGISTRY

    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"mcp config not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    registry = MCPRegistry()
    for entry in data.get("servers", []):
        if not entry.get("enabled", True):
            continue
        config = MCPServerConfig(
            name=entry["name"],
            command=entry["command"],
            args=entry.get("args", []),
            env=entry.get("env", {}),
        )
        try:
            registry.add_server(config)
        except Exception as exc:
            print(f"[mcp] failed to connect '{config.name}': {exc}", flush=True)
    _GLOBAL_REGISTRY = registry
    return registry


def get_registry() -> MCPRegistry | None:
    return _GLOBAL_REGISTRY


def call_mcp_tool(qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if _GLOBAL_REGISTRY is None:
        return {"error": "MCP not initialized — pass --with-mcp"}
    return _GLOBAL_REGISTRY.call(qualified_name, arguments)
