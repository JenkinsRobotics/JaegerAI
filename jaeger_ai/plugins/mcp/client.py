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
from concurrent.futures import TimeoutError as FutureTimeout
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
logger = logging.getLogger(__name__)


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
    # "oauth" turns on the ported OAuth flow for an HTTP server (see
    # jaeger_ai/plugins/mcp/oauth.py). Empty = static headers only, which
    # is the pre-existing behaviour.
    auth: str = ""
    scope: str = ""
    # Per-server limits for big servers (REA exposes ~207 tools).
    #   tools_include: exact names or fnmatch globs to keep (empty = all)
    #   tools_exclude: names/globs to drop after include
    #   max_tools:     hard cap after filtering (0 = no cap)
    #   gated:         registered and callable, but hidden from a turn's
    #                  schema unless that turn's allowlist names the tool or
    #                  the server's toolset was loaded (``load_tools``)
    tools_include: list[str] = field(default_factory=list)
    tools_exclude: list[str] = field(default_factory=list)
    max_tools: int = 0
    gated: bool = False
    #   tools_read_only: names/globs the owner declares read-only. Only these
    #                  run without an approval card; every other tool of the
    #                  server asks through the live confirmation provider.
    #                  Server annotations (readOnlyHint) are not trusted.
    tools_read_only: list[str] = field(default_factory=list)
    connect_timeout_s: float = 20.0
    call_timeout_s: float = 60.0


DEFAULT_CONNECT_TIMEOUT_S = 20.0
DEFAULT_CALL_TIMEOUT_S = 60.0
MAX_TIMEOUT_S = 3600.0


def _timeout(value: Any, default: float) -> float:
    """A per-server timeout from mcp.json, bounded to (0, MAX_TIMEOUT_S]."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number <= 0:
        return default
    return min(number, MAX_TIMEOUT_S)


def _name_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and str(item).strip()]


def _match_any(name: str, patterns: list[str]) -> bool:
    import fnmatch
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def is_read_only_tool(tool_name: str, config: "MCPServerConfig") -> bool:
    """True only when the owner listed ``tool_name`` under ``tools.read_only``."""
    return bool(tool_name) and _match_any(tool_name, config.tools_read_only)


def filter_tool_names(names: list[str], config: "MCPServerConfig") -> list[str]:
    """Apply a server's include/exclude/max limits, keeping server order."""
    _match = _match_any

    kept = [n for n in names if not config.tools_include or _match(n, config.tools_include)]
    kept = [n for n in kept if not _match(n, config.tools_exclude)]
    if config.max_tools and config.max_tools > 0:
        kept = kept[: int(config.max_tools)]
    return kept


def server_config_from_entry(entry: dict[str, Any], *, env: dict[str, str] | None = None,
                             headers: dict[str, str] | None = None) -> "MCPServerConfig":
    """Build an MCPServerConfig from one mcp.json row (limits + timeouts included)."""
    tools = entry.get("tools") if isinstance(entry.get("tools"), dict) else {}
    try:
        max_tools = max(0, int(tools.get("max") or entry.get("max_tools") or 0))
    except (TypeError, ValueError):
        max_tools = 0
    return MCPServerConfig(
        name=str(entry.get("name") or "unknown"),
        command=entry.get("command"),
        args=list(entry.get("args", []) or []),
        env=dict(env if env is not None else entry.get("env", {}) or {}),
        url=entry.get("url"),
        headers=dict(headers if headers is not None else entry.get("headers", {}) or {}),
        auth=str(entry.get("auth", "") or ""),
        scope=str(entry.get("scope", "") or ""),
        tools_include=_name_list(tools.get("include")),
        tools_exclude=_name_list(tools.get("exclude")),
        max_tools=max_tools,
        gated=bool(tools.get("gated", False)),
        tools_read_only=_name_list(tools.get("read_only")),
        connect_timeout_s=_timeout(entry.get("connect_timeout_s"), DEFAULT_CONNECT_TIMEOUT_S),
        call_timeout_s=_timeout(entry.get("call_timeout_s"), DEFAULT_CALL_TIMEOUT_S),
    )


@dataclass
class MCPToolSpec:
    qualified_name: str          # "mcp:web/fetch"
    server_name: str             # "web"
    tool_name: str               # "fetch"
    description: str
    input_schema: dict[str, Any]
    agent_name: str = ""
    read_only: bool = False      # owner-declared (tools.read_only); False = ask


def _agent_tool_name(server: str, tool: str) -> str:
    """Return a provider-safe function name while retaining MCP provenance."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{server}__{tool}")[:64]


def check_mcp_permission(spec: MCPToolSpec, arguments: dict[str, Any]) -> None:
    """Gate one MCP call on the live PermissionPolicy (the same check
    ``requires_tier`` runs for native tools, so the Gateway's approval card).

    Owner-declared read-only tools check at READ_ONLY (allowed unless the
    policy is paused). Every other tool checks at EXTERNAL_EFFECT with a
    per-tool skill id ``mcp:<server>/<tool>``: a specialist allowlist or a
    grant naming only the server does not approve it; an "always" answer
    applies to that one tool. Raises PermissionDenied when refused."""
    from jaeger_os.core.safety.permissions import PermissionRequest, PermissionTier, current_policy

    tier = PermissionTier.READ_ONLY if spec.read_only else PermissionTier.EXTERNAL_EFFECT
    current_policy().check(PermissionRequest(
        tier=tier,
        skill=f"mcp:{spec.server_name}/{spec.tool_name}",
        operation=spec.agent_name or spec.tool_name,
        summary=f"MCP {spec.server_name}: {spec.tool_name}"
                + ("" if spec.read_only else " (not declared read-only)"),
        arguments=dict(arguments or {}),
    ))


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

        check_mcp_permission(spec, arguments if isinstance(arguments, dict) else {})
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
        self.resources_advertised = False

    async def connect(self) -> list[Any]:
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        self._exit_stack = AsyncExitStack()
        if self.config.url:
            import httpx
            from mcp.client.streamable_http import streamable_http_client

            # Redirects are deliberately disabled so credentials cannot be
            # forwarded to a different origin by a configured endpoint.
            # OAuth (ported from hermes-agent). The SDK's OAuthClientProvider
            # is an httpx auth flow, so it attaches here and transparently
            # handles the 401 → refresh → retry cycle. None when the server
            # is configured with static headers, leaving that path untouched.
            auth_flow = None
            if self.config.url:
                try:
                    from jaeger_ai.plugins.mcp import oauth as _oauth
                    if _oauth.server_uses_oauth(self.config):
                        auth_flow = _oauth.get_manager().provider(
                            self.config.name, self.config.url,
                            scope=self.config.scope)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "mcp: OAuth setup failed for %r (%s) — connecting "
                        "without it", self.config.name, exc)
            http_client = await self._exit_stack.enter_async_context(httpx.AsyncClient(
                headers=self.config.headers,
                follow_redirects=False,
                timeout=httpx.Timeout(30.0, read=300.0),
                auth=auth_flow,
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
        initialization = await self._session.initialize()
        self.resources_advertised = getattr(getattr(initialization,"capabilities",None),"resources",None) is not None
        listing = await self._session.list_tools()
        return list(listing.tools)

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return await self._session.call_tool(tool_name, arguments)

    async def list_resources(self, cursor: str | None = None) -> Any:
        return await self._session.list_resources(cursor=cursor)

    async def read_resource(self, uri: str) -> Any:
        from pydantic import AnyUrl
        return await self._session.read_resource(AnyUrl(uri))

    async def close(self, *, strict: bool = False) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:
                if strict:
                    raise


class MCPRegistry:
    """Holds clients, runs the async loop, exposes a sync API."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True, name="mcp-loop")
        self._loop_thread.start()
        self._clients: dict[str, _MCPClient] = {}
        self._tools: dict[str, MCPToolSpec] = {}
        self._lifecycle_lock = threading.RLock()
        self._active_calls: dict[str, int] = {}
        self._server_states: dict[str, str] = {}
        self._disconnected: dict[str, MCPServerConfig] = {}
        self._resource_handles: dict[tuple[str,str],dict[str,str]] = {}
        self._resource_pages: dict[tuple[str,str],str] = {}
        self._resource_snapshots: dict[str,dict[str,Any]] = {}

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Any, timeout: float, *, cancellation: threading.Event | None = None) -> Any:
        if cancellation is not None and cancellation.is_set():
            coro.close()
            raise RuntimeError("MCP call cancelled before dispatch")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        deadline = time.monotonic() + timeout
        while True:
            if cancellation is not None and cancellation.is_set():
                # Cancel this SDK request, never the shared server/transport.
                # Remote cancellation is best effort; leave the effect ledger
                # claim pending rather than reporting that the effect stopped.
                future.cancel()
                raise RuntimeError("MCP call interrupted; remote outcome unconfirmed; do not retry")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                future.cancel()
                raise RuntimeError("MCP call timed out; remote outcome unconfirmed; do not retry")
            try:
                return future.result(timeout=min(0.1, remaining))
            except FutureTimeout:
                if future.done():
                    raise

    def add_server(self, config: MCPServerConfig, *, connect_timeout: float | None = None) -> list[MCPToolSpec]:
        client = _MCPClient(config)
        started = time.perf_counter()
        timeout = connect_timeout if connect_timeout is not None else config.connect_timeout_s
        tools = self._submit(client.connect(), timeout=timeout)
        elapsed = time.perf_counter() - started
        offered = len(tools)
        keep = set(filter_tool_names([t.name for t in tools], config))
        tools = [t for t in tools if t.name in keep]
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
                read_only=is_read_only_tool(tool.name, config),
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
        try:
            from jaeger_agent.skill_registry.toolset_scoping import register_mcp_server_toolset
            register_mcp_server_toolset(config.name, [s.agent_name for s in specs], gated=config.gated)
        except Exception:  # noqa: BLE001 — visibility bookkeeping must not drop a connected server
            pass
        limited = f" (of {offered} offered)" if offered != len(specs) else ""
        gated = " gated" if config.gated else ""
        print(f"[mcp] connected to '{config.name}' in {elapsed:.2f}s — {len(specs)}{gated} tool(s){limited}", flush=True)
        return specs

    def call(self, qualified_name: str, arguments: dict[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        with self._lifecycle_lock:
            spec = self._tools.get(qualified_name)
            if spec is None:
                raise ValueError(f"unknown MCP tool: {qualified_name}")
            if self._server_states.get(spec.server_name, 'loaded_not_probed') != 'loaded_not_probed':
                raise RuntimeError('MCP server lifecycle or prior outcome requires reconciliation; no call dispatched')
            client = self._clients[spec.server_name]
            self._active_calls[spec.server_name] = self._active_calls.get(spec.server_name, 0) + 1
        try:
            if timeout is None:
                timeout = client.config.call_timeout_s
            secrets = set(client.config.headers.values())
            secrets.update(
                value
                for key, value in client.config.env.items()
                if _SECRET_NAME.search(key)
            )
            from jaeger_agent.core.cancellation import current_cancellation
            try:
                result = self._submit(client.call(spec.tool_name, arguments), timeout=timeout,
                                      cancellation=current_cancellation())
            except Exception as exc:
                # A lost response can follow a real external effect. Never replay
                # it automatically, including after cancellation or timeout.
                with self._lifecycle_lock:
                    self._server_states[spec.server_name] = "outcome_unknown"
                raise RuntimeError(_redact_known_secrets(str(exc), secrets)) from None
            payload = _result_to_dict(result)
            return _redact_known_secrets(payload, secrets)

        finally:
            with self._lifecycle_lock:
                self._active_calls[spec.server_name] -= 1

    @staticmethod
    def control_id(name: str) -> str:
        import hashlib
        return hashlib.sha256(name.encode()).hexdigest()[:24]

    def lifecycle(self, control_id: str, action: str, expected_state: str) -> dict[str, Any]:
        """Only disconnect/reconnect an already-loaded owner's unchanged config.

        No config/credentials/permissions from HTTP. Unknown remote outcomes or
        active calls forbid lifecycle operations; transport close is not cancellation.
        """
        with self._lifecycle_lock:
            names = set(self._clients) | set(self._disconnected)
            name = next((n for n in names if self.control_id(n) == control_id), None)
            if name is None:
                raise ValueError('Loaded MCP connection not found')
            state = self._server_states.get(name, 'loaded_not_probed')
            allowed = {'disconnect': 'loaded_not_probed', 'reconnect': 'disconnected'}
            if action not in allowed or state != allowed[action] or state != expected_state:
                raise ValueError('MCP connection changed or outcome is uncertain; refresh without replay')
            if self._active_calls.get(name, 0):
                raise ValueError('MCP calls are active; connection retained')
            self._server_states[name] = 'disconnecting' if action == 'disconnect' else 'connecting'
        try:
            if action == 'disconnect':
                client = self._clients[name]
                self._submit(client.close(strict=True), timeout=10)
                from jaeger_os.core.tools.tool_registry import unregister_tool
                from jaeger_agent.skill_registry.toolset_scoping import unregister_mcp_server_toolset
                with self._lifecycle_lock:
                    for key, spec in list(self._tools.items()):
                        if spec.server_name == name:
                            unregister_tool(spec.agent_name)
                            del self._tools[key]
                    unregister_mcp_server_toolset(name)
                    self._disconnected[name] = client.config
                    del self._clients[name]
                    self._server_states[name] = 'disconnected'
                    self._resource_handles = {key:value for key,value in self._resource_handles.items() if key[0]!=name}
                    self._resource_pages = {key:value for key,value in self._resource_pages.items() if key[0]!=name}
                    self._resource_snapshots = {key:value for key,value in self._resource_snapshots.items() if value['server_id']!=control_id}
            else:
                self.add_server(self._disconnected[name])
                with self._lifecycle_lock:
                    del self._disconnected[name]
                    self._server_states[name] = 'loaded_not_probed'
            return {'id': control_id, 'state': self._server_states[name], 'delivery_verified': False}
        except Exception:
            with self._lifecycle_lock:
                self._server_states[name] = 'outcome_unknown'
            raise RuntimeError('MCP lifecycle outcome unknown; automatic retry is disabled') from None

    def list_tools(self) -> list[MCPToolSpec]:
        return list(self._tools.values())

    def has_tool(self, qualified_name: str) -> bool:
        return qualified_name in self._tools

    def shutdown(self) -> None:
        from jaeger_os.core.tools.tool_registry import unregister_tool
        for spec in self._tools.values():
            unregister_tool(spec.agent_name)
        try:
            from jaeger_agent.skill_registry.toolset_scoping import unregister_mcp_server_toolset
            for server in self._clients:
                unregister_mcp_server_toolset(server)
        except Exception:  # noqa: BLE001
            pass
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


def init_from_config(config_path: Path | None = None, *, layout: Any = None,
                     only: Any = None) -> MCPRegistry:
    """Initialize the global MCP registry from a JSON config file.

    ``only`` (optional predicate on a server row) limits which servers start."""
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
        if only is not None and not only(entry):
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
            config = server_config_from_entry(entry, env=env, headers=headers)
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


def runtime_inventory() -> dict[str, Any]:
    """Snapshot loaded connections/tools without connecting or exposing config.

    Reuse loaded secret values for redaction; never return command, URL, args,
    environment, headers, input defaults or connection exception strings.
    """
    from jaeger_ai.core.redaction import redact_text
    registry = get_registry()
    if registry is None:
        return {"initialized": False, "servers": [], "tools": []}
    with registry._lifecycle_lock:
        clients = list(registry._clients.items())
        disconnected = list(registry._disconnected.items())
        states = dict(registry._server_states)
        active = dict(registry._active_calls)
    secrets = set()
    for config in [client.config for _, client in clients] + [config for _, config in disconnected]:
        secrets.update(config.headers.values())
        secrets.update(value for key, value in config.env.items() if _SECRET_NAME.search(key))
    def safe(value: str) -> str:
        return redact_text(_redact_known_secrets(str(value), secrets))[:1000]
    specs = registry.list_tools()
    servers = []
    for name in sorted({n for n, _ in clients} | {n for n, _ in disconnected}):
        state = states.get(name, 'loaded_not_probed')
        actions = [] if active.get(name, 0) else ['disconnect'] if state == 'loaded_not_probed' else ['reconnect'] if state == 'disconnected' else []
        servers.append({'id': registry.control_id(name), 'name': safe(name), 'state': state,
                        'tool_count': sum(t.server_name == name for t in specs), 'active_calls': active.get(name, 0), 'resources_advertised':bool(getattr(registry._clients.get(name),'resources_advertised',False)), 'actions': actions})
    loaded_names = {name for name, _ in clients}
    servers.extend({"name": safe(name), "state": "connection_failed", "tool_count": 0} for name in connection_errors() if name not in loaded_names)
    tools = [{"agent_name": t.agent_name, "display_name": safe(t.agent_name), "server": safe(t.server_name), "description": safe(t.description)} for t in specs]
    return {"initialized": True, "servers": servers, "tools": tools}
