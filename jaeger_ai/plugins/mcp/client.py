"""MCP (Model Context Protocol) bridge — opt-in extension.

Goal: keep our fast in-process tools as the default path, and add MCP servers
as opt-in extended capability. This module owns the async-to-sync bridge so
the rest of the agent can stay synchronous.

Architecture:
- A persistent asyncio event loop runs in a daemon thread
- Each configured MCP server gets an MCPClient that holds an open transport session
- Sync calls are submitted as coroutines and awaited via run_coroutine_threadsafe
- Tools are registered globally with names like "mcp:<server>/<tool>"

This module is only imported when --with-mcp is set; default agent paths
pay zero cost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Quiet down the mcp SDK's own logging unless something goes wrong.
logging.getLogger("mcp").setLevel(logging.WARNING)


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = ROOT / "mcp_config.json"
_SECRET_NAME = re.compile(
    r"(authorization|cookie|token|secret|password|api[_-]?key|credential)",
    re.IGNORECASE,
)
_MASK = "********"


def _redact_known_secrets(value: Any, secrets: set[str]) -> Any:
    """Remove configured MCP credentials from tool results and errors."""
    if isinstance(value, str):
        redacted = value
        for secret in sorted((item for item in secrets if len(item) >= 4), key=len, reverse=True):
            redacted = redacted.replace(secret, _MASK)
        return redacted
    if isinstance(value, dict):
        return {key: _redact_known_secrets(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_known_secrets(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_known_secrets(item, secrets) for item in value)
    return value


@dataclass
class MCPServerConfig:
    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPToolSpec:
    qualified_name: str          # "mcp:web/fetch"
    server_name: str             # "web"
    tool_name: str               # "fetch"
    description: str
    input_schema: dict[str, Any]
    agent_name: str = ""


def _agent_tool_name(server: str, tool: str) -> str:
    """Return a provider-safe function name while retaining MCP provenance."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{server}__{tool}")[:64]


def _register_agent_tool(spec: MCPToolSpec) -> None:
    """Expose a connected MCP tool through Jaeger's canonical registry."""
    from jaeger_os.core.tools.tool_registry import (
        ToolDef,
        has_tool,
        register_tool_instance,
    )
    from pydantic import BaseModel, ConfigDict

    schema = dict(spec.input_schema or {"type": "object", "properties": {}})

    class MCPArguments(BaseModel):
        model_config = ConfigDict(extra="allow")

        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return schema

    def invoke(**arguments: Any) -> dict[str, Any]:
        # Unwrap _raw_arguments if model passed JSON string (including concatenated JSON objects)
        if "_raw_arguments" in arguments and len(arguments) == 1:
            raw = arguments["_raw_arguments"]
            if isinstance(raw, str):
                s = raw.strip()
                merged: dict[str, Any] = {}
                decoder = json.JSONDecoder()
                while s:
                    s = s.lstrip()
                    if not s:
                        break
                    try:
                        obj, idx = decoder.raw_decode(s)
                        if isinstance(obj, dict):
                            merged.update(obj)
                        s = s[idx:].lstrip()
                    except Exception:
                        break
                if merged:
                    arguments = merged
        elif "arguments" in arguments and isinstance(arguments["arguments"], dict) and len(arguments) == 1:
            arguments = arguments["arguments"]

        # Clean quotes and spaces from dictionary keys
        if isinstance(arguments, dict):
            arguments = {
                str(k).strip().strip('"').strip("'"): v
                for k, v in arguments.items()
            }

        # Best-effort schema validation; do not block dispatch if it drifts
        try:
            import jsonschema
            jsonschema.validate(arguments, schema)
        except Exception:
            pass

        return call_mcp_tool(spec.qualified_name, arguments)

    if has_tool(spec.agent_name):
        raise ValueError(f"MCP tool name collides with an existing tool: {spec.agent_name}")
    register_tool_instance(ToolDef(name=spec.agent_name, description=spec.description,
                                   args_model=MCPArguments, fn=invoke,
                                   side_effect="external"))


class _MCPClient:
    """One MCP server connection. The session stays open for the process lifetime."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: Any = None
        self._exit_stack: Any = None

    async def connect(self) -> list[Any]:
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        self._exit_stack = AsyncExitStack()
        if self.config.url:
            import httpx
            from mcp.client.streamable_http import streamable_http_client

            # Redirects are deliberately disabled so credentials cannot be
            # forwarded to a different origin by a configured endpoint.
            http_client = await self._exit_stack.enter_async_context(httpx.AsyncClient(
                headers=self.config.headers,
                follow_redirects=False,
                timeout=httpx.Timeout(30.0, read=300.0),
            ))
            transport = await self._exit_stack.enter_async_context(
                streamable_http_client(self.config.url, http_client=http_client))
            read, write = transport[0], transport[1]
        else:
            from mcp.client.stdio import StdioServerParameters, stdio_client

            inherited = {key: value for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
                         if (value := os.environ.get(key))}
            params = StdioServerParameters(
                command=self.config.command or "",
                args=self.config.args,
                env={**inherited, **self.config.env},
            )
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
                agent_name=_agent_tool_name(config.name, tool.name),
            )
            specs.append(spec)
        registered: list[MCPToolSpec] = []
        try:
            for spec in specs:
                _register_agent_tool(spec)
                registered.append(spec)
                self._tools[spec.qualified_name] = spec
        except Exception:
            from jaeger_os.core.tools.tool_registry import unregister_tool
            for spec in registered:
                unregister_tool(spec.agent_name)
                self._tools.pop(spec.qualified_name, None)
            try:
                self._submit(client.close(), timeout=5.0)
            except Exception:
                pass
            raise
        self._clients[config.name] = client
        print(f"[mcp] connected to '{config.name}' in {elapsed:.2f}s — {len(specs)} tool(s)", flush=True)
        return specs

    def call(self, qualified_name: str, arguments: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
        spec = self._tools.get(qualified_name)
        if spec is None:
            raise ValueError(f"unknown MCP tool: {qualified_name}")
        client = self._clients[spec.server_name]
        secrets = set(client.config.headers.values())
        secrets.update(
            value
            for key, value in client.config.env.items()
            if _SECRET_NAME.search(key)
        )
        try:
            result = self._submit(client.call(spec.tool_name, arguments), timeout=timeout)
        except Exception as exc:
            # Resilient retry for transient pipe/IPC timeouts during heavy batch tasks
            try:
                time.sleep(0.1)
                result = self._submit(client.call(spec.tool_name, arguments), timeout=timeout)
            except Exception as retry_exc:
                raise RuntimeError(_redact_known_secrets(str(retry_exc), secrets)) from None
        payload = _result_to_dict(result)
        return _redact_known_secrets(payload, secrets)

    def list_tools(self) -> list[MCPToolSpec]:
        return list(self._tools.values())

    def has_tool(self, qualified_name: str) -> bool:
        return qualified_name in self._tools

    def shutdown(self) -> None:
        from jaeger_os.core.tools.tool_registry import unregister_tool
        for spec in self._tools.values():
            unregister_tool(spec.agent_name)
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
_LAST_ERRORS: dict[str, str] = {}


def init_from_config(config_path: Path | None = None, *, layout: Any = None) -> MCPRegistry:
    """Initialize the global MCP registry from a JSON config file."""
    global _GLOBAL_REGISTRY, _LAST_ERRORS
    if _GLOBAL_REGISTRY is not None:
        return _GLOBAL_REGISTRY

    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"mcp config not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    registry = MCPRegistry()
    errors: dict[str, str] = {}
    for entry in data.get("servers", []):
        if not entry.get("enabled", True):
            continue
        name = str(entry.get("name") or "unknown")
        env: dict[str, str] = {}
        headers: dict[str, str] = {}
        try:
            env = entry.get("env", {})
            headers = entry.get("headers", {})
            if layout is not None:
                from jaeger_ai.core.mcp.service import (
                    resolve_server_env,
                    resolve_server_headers,
                )
                env = resolve_server_env(layout, entry)
                headers = resolve_server_headers(layout, entry)
            config = MCPServerConfig(
                name=name,
                command=entry.get("command"),
                args=entry.get("args", []),
                env=env,
                url=entry.get("url"),
                headers=headers,
            )
            registry.add_server(config)
        except Exception as exc:
            secrets = {
                value
                for value in headers.values()
                if isinstance(value, str)
            } if isinstance(headers, dict) else set()
            if isinstance(env, dict):
                secrets.update(
                    value
                    for key, value in env.items()
                    if isinstance(value, str) and _SECRET_NAME.search(str(key))
                )
            safe_error = _redact_known_secrets(str(exc), secrets)
            errors[name] = safe_error
            print(f"[mcp] failed to connect '{name}': {safe_error}", flush=True)
    _GLOBAL_REGISTRY = registry
    _LAST_ERRORS = errors
    return registry


def get_registry() -> MCPRegistry | None:
    return _GLOBAL_REGISTRY


def connection_errors() -> dict[str, str]:
    return dict(_LAST_ERRORS)


def reload_from_config(config_path: Path, *, layout: Any = None) -> MCPRegistry:
    """Replace the live registry with the instance-owned configuration."""
    global _GLOBAL_REGISTRY, _LAST_ERRORS
    previous = _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = None
    _LAST_ERRORS = {}
    if previous is not None:
        previous.shutdown()
    return init_from_config(config_path, layout=layout)


def shutdown_global() -> None:
    """Release subprocesses, unregister tools, and clear singleton state."""
    global _GLOBAL_REGISTRY, _LAST_ERRORS
    registry = _GLOBAL_REGISTRY
    _GLOBAL_REGISTRY = None
    _LAST_ERRORS = {}
    if registry is not None:
        registry.shutdown()


def call_mcp_tool(qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if _GLOBAL_REGISTRY is None:
        return {"error": "MCP not initialized — pass --with-mcp"}
    return _GLOBAL_REGISTRY.call(qualified_name, arguments)
