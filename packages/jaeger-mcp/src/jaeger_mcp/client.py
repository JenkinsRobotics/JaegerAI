"""Live MCP client manager backed by the official ``mcp`` SDK (stdio, Streamable HTTP, SSE).

Combines Hermes-style server discovery, liveness tracking, secret redaction,
and Codex-style 8KB/64KB schema budgets with zero idle overhead when no servers
are configured. Runs its async client sessions on a dedicated daemon event-loop
thread so sync ``ToolRegistry`` handlers can call live MCP tools safely.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import threading
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .budget import enforce_mcp_schema_budget
from .policy import agent_tool_name, redact_secrets
from .sandbox import wrap_stdio_with_seatbelt

MAX_MCP_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB hard cap per image block
_MIME_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
}


def extract_mcp_content(
    content_items: Sequence[Any],
    *,
    image_dir: Path | None = None,
    server_name: str = "",
    tool_name: str = "",
    secrets: set[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Extract text and preserve MCP ImageContent/Resource blocks without base64 context bloat.

    When ``image_dir`` is provided, decoded image bytes are persisted to disk so
    vision tools and UIs can inspect rendered geometry (e.g. Aether-CAD viewport PNGs)
    without dumping raw base64 payloads into the LLM prompt.
    """
    parts: list[str] = []
    images: list[dict[str, Any]] = []
    safe_srv = re.sub(r"[^a-zA-Z0-9_-]+", "_", server_name or "mcp")[:24]
    safe_tool = re.sub(r"[^a-zA-Z0-9_-]+", "_", tool_name or "tool")[:32]

    for idx, item in enumerate(content_items or ()):
        itype = str(getattr(item, "type", None) or (item.get("type") if isinstance(item, Mapping) else "") or "").lower()
        mime = str(
            getattr(item, "mimeType", None)
            or getattr(item, "mime_type", None)
            or (item.get("mimeType") if isinstance(item, Mapping) else None)
            or (item.get("mime_type") if isinstance(item, Mapping) else None)
            or ""
        ).lower()
        data_b64 = getattr(item, "data", None)
        if data_b64 is None and isinstance(item, Mapping):
            data_b64 = item.get("data")

        # Handle embedded binary resource images too
        res_obj = getattr(item, "resource", None)
        if res_obj is None and isinstance(item, Mapping):
            res_obj = item.get("resource")
        if res_obj is not None and not data_b64:
            r_mime = str(
                getattr(res_obj, "mimeType", None)
                or (res_obj.get("mimeType") if isinstance(res_obj, Mapping) else "")
                or ""
            ).lower()
            r_blob = getattr(res_obj, "blob", None)
            if r_blob is None and isinstance(res_obj, Mapping):
                r_blob = res_obj.get("blob")
            if r_mime.startswith("image/") and isinstance(r_blob, str) and r_blob:
                mime = r_mime
                data_b64 = r_blob
                itype = "image"

        if (itype == "image" or mime.startswith("image/")) and isinstance(data_b64, str) and data_b64.strip():
            resolved_mime = mime if mime.startswith("image/") else "image/png"
            ext = _MIME_EXT.get(resolved_mime, "png")
            raw_bytes: bytes | None = None
            try:
                raw_bytes = base64.b64decode(data_b64.strip(), validate=False)
            except Exception:  # noqa: BLE001
                raw_bytes = None
            if raw_bytes is not None and len(raw_bytes) <= MAX_MCP_IMAGE_BYTES:
                sha = hashlib.sha256(raw_bytes).hexdigest()[:16]
                saved_path = ""
                if image_dir is not None:
                    try:
                        image_dir.mkdir(parents=True, exist_ok=True)
                        fname = f"{safe_srv}_{safe_tool}_{int(time.time() * 1000)}_{idx}_{sha[:8]}.{ext}"
                        target = image_dir / fname
                        target.write_bytes(raw_bytes)
                        saved_path = str(target)
                    except OSError:
                        saved_path = ""
                meta = {
                    "mime_type": resolved_mime,
                    "bytes": len(raw_bytes),
                    "sha256": sha,
                    "path": saved_path,
                    "server": server_name,
                    "tool": tool_name,
                }
                images.append(meta)
                if saved_path:
                    parts.append(f"[MCP Image saved: {saved_path} ({resolved_mime}, {len(raw_bytes)} bytes)]")
                else:
                    parts.append(f"[MCP Image received: {resolved_mime}, {len(raw_bytes)} bytes, sha256={sha}]")
                continue

        txt = getattr(item, "text", None)
        if txt is None and isinstance(item, Mapping):
            txt = item.get("text")
        parts.append(str(txt) if txt is not None else str(item))

    return redact_secrets("\n".join(parts), secrets or set()), images


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"  # "stdio" | "streamable_http" | "sse"
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    url: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_s: float = 30.0
    enabled: bool = True
    sandbox_workspace: str = ""


@dataclass
class MCPServerHealth:
    name: str
    transport: str
    connected: bool
    tools_count: int = 0
    error: str = ""
    last_checked_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "connected": self.connected,
            "tools_count": self.tools_count,
            "error": self.error,
            "last_checked_at": self.last_checked_at,
        }


def load_mcp_server_configs(config_path: Path) -> list[MCPServerConfig]:
    """Load MCP server specs from ``mcp_servers.json`` (supports Claude/Cursor/Jaeger schema)."""
    if not config_path.is_file():
        return []
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    servers_obj = raw.get("mcpServers") if isinstance(raw, dict) and "mcpServers" in raw else raw
    if not isinstance(servers_obj, dict):
        return []
    configs: list[MCPServerConfig] = []
    for name, spec in servers_obj.items():
        if not isinstance(spec, dict) or spec.get("enabled") is False:
            continue
        url = str(spec.get("url") or "").strip()
        cmd = str(spec.get("command") or "").strip()
        transport = str(spec.get("transport") or ("streamable_http" if url else "stdio")).strip().lower()
        configs.append(
            MCPServerConfig(
                name=str(name),
                transport=transport,
                command=cmd,
                args=tuple(str(a) for a in (spec.get("args") or ())),
                env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
                url=url,
                headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items()},
                timeout_s=float(spec.get("timeout_s") or 30.0),
                enabled=True,
                sandbox_workspace=str(spec.get("sandbox_workspace") or ""),
            )
        )
    return configs


def save_mcp_server_config(config_path: Path, cfg: MCPServerConfig) -> list[MCPServerConfig]:
    """Persist or update one MCP server entry in ``mcp_servers.json`` (Claude/Cursor/Jaeger format)."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    raw: dict[str, Any] = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:  # noqa: BLE001
            raw = {}
    servers = raw.get("mcpServers") if isinstance(raw.get("mcpServers"), dict) else {}
    entry: dict[str, Any] = {
        "transport": cfg.transport,
        "enabled": cfg.enabled,
        "timeout_s": cfg.timeout_s,
    }
    if cfg.command:
        entry["command"] = cfg.command
        entry["args"] = list(cfg.args)
    if cfg.env:
        entry["env"] = dict(cfg.env)
    if cfg.url:
        entry["url"] = cfg.url
    if cfg.headers:
        entry["headers"] = dict(cfg.headers)
    if cfg.sandbox_workspace:
        entry["sandbox_workspace"] = cfg.sandbox_workspace
    servers[cfg.name] = entry
    raw["mcpServers"] = servers
    tmp = config_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, config_path)
    return load_mcp_server_configs(config_path)


def remove_mcp_server_config(config_path: Path, name: str) -> list[MCPServerConfig]:
    """Remove an MCP server entry by name from ``mcp_servers.json``."""
    if not config_path.is_file():
        return []
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if isinstance(raw, dict) and isinstance(raw.get("mcpServers"), dict):
        raw["mcpServers"].pop(name, None)
        tmp = config_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, config_path)
    return load_mcp_server_configs(config_path)


class LiveMCPManager:
    """Manages live MCP client sessions, schema budgets, health probes, and tool calls."""

    def __init__(self, configs: Sequence[MCPServerConfig] = (), *, image_dir: Path | None = None) -> None:
        self._configs: dict[str, MCPServerConfig] = {c.name: c for c in configs if c.enabled}
        self._image_dir: Path | None = Path(image_dir).expanduser().resolve() if image_dir is not None else None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stacks: dict[str, AsyncExitStack] = {}
        self._sessions: dict[str, Any] = {}
        self._health: dict[str, MCPServerHealth] = {
            c.name: MCPServerHealth(name=c.name, transport=c.transport, connected=False)
            for c in self._configs.values()
        }
        self._discovered_tools: list[dict[str, Any]] = []

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                t = threading.Thread(target=loop.run_forever, name="jaeger-mcp-loop", daemon=True)
                t.start()
                self._loop = loop
                self._thread = t
            return self._loop

    def _run(self, coro: Any, timeout: float = 35.0) -> Any:
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    async def _connect_one(self, cfg: MCPServerConfig) -> list[dict[str, Any]]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        try:
            if cfg.transport == "stdio":
                cmd = cfg.command
                args = list(cfg.args)
                if cfg.sandbox_workspace and os.uname().sysname == "Darwin":
                    wrapped = wrap_stdio_with_seatbelt([cmd, *args], workspace=cfg.sandbox_workspace)
                    cmd, args = wrapped[0], wrapped[1:]
                env = {**os.environ, **dict(cfg.env)} if cfg.env else None
                params = StdioServerParameters(command=cmd, args=args, env=env)
                read, write = await stack.enter_async_context(stdio_client(params))
            elif cfg.transport == "streamable_http":
                from mcp.client.streamable_http import streamablehttp_client

                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(cfg.url, headers=dict(cfg.headers) or None)
                )
            elif cfg.transport == "sse":
                from mcp.client.sse import sse_client

                read, write = await stack.enter_async_context(
                    sse_client(cfg.url, headers=dict(cfg.headers) or None)
                )
            else:
                raise ValueError(f"Unsupported MCP transport: {cfg.transport!r}")

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            raw_tools: list[dict[str, Any]] = []
            for t in getattr(listed, "tools", []) or []:
                raw_tools.append({
                    "server": cfg.name,
                    "original_name": t.name,
                    "name": agent_tool_name(cfg.name, t.name),
                    "description": str(t.description or ""),
                    "schema": dict(getattr(t, "inputSchema", None) or {"type": "object", "properties": {}}),
                })
            kept, _report = enforce_mcp_schema_budget(raw_tools)
            self._stacks[cfg.name] = stack
            self._sessions[cfg.name] = session
            self._health[cfg.name] = MCPServerHealth(
                name=cfg.name,
                transport=cfg.transport,
                connected=True,
                tools_count=len(kept),
                last_checked_at=time.time(),
            )
            return list(kept)
        except Exception as exc:  # noqa: BLE001
            await stack.aclose()
            self._health[cfg.name] = MCPServerHealth(
                name=cfg.name,
                transport=cfg.transport,
                connected=False,
                error=redact_secrets(str(exc))[:300],
                last_checked_at=time.time(),
            )
            return []

    def connect_all(self) -> list[dict[str, Any]]:
        """Connect to all enabled configured MCP servers and return budget-enforced tool specs."""
        if not self._configs:
            return []
        all_tools: list[dict[str, Any]] = []
        for cfg in self._configs.values():
            all_tools.extend(self._run(self._connect_one(cfg), timeout=cfg.timeout_s + 5.0))
        self._discovered_tools = all_tools
        return list(all_tools)

    def call_tool(self, server_name: str, tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        session = self._sessions.get(server_name)
        if session is None:
            return {"ok": False, "error": f"MCP server '{server_name}' is not connected"}

        cfg = self._configs.get(server_name)
        known_secrets: set[str] = set()
        if cfg is not None:
            known_secrets.update(v for v in cfg.headers.values() if v)
            known_secrets.update(v for v in cfg.env.values() if v)

        async def _invoke() -> dict[str, Any]:
            res = await session.call_tool(tool_name, dict(arguments or {}))
            output, images = extract_mcp_content(
                getattr(res, "content", []) or [],
                image_dir=self._image_dir,
                server_name=server_name,
                tool_name=tool_name,
                secrets=known_secrets,
            )
            is_err = bool(getattr(res, "isError", False))
            return {
                "ok": not is_err,
                "output": output,
                "images": images,
                "error": output if is_err else None,
            }

        timeout = cfg.timeout_s if cfg else 30.0
        try:
            return self._run(_invoke(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": redact_secrets(str(exc), known_secrets)}

    def register_into_registry(self, registry: Any) -> int:
        """Connect configured MCP servers and register every discovered tool into a ToolRegistry."""
        tools = self.connect_all()
        count = 0
        for spec in tools:
            srv = spec["server"]
            orig = spec["original_name"]
            namespaced = spec["name"]

            from jaeger_contracts import ToolResult
            from jaeger_tools import ToolSpec

            def _make_handler(s: str, o: str, n: str):
                def _handler(args: Mapping[str, Any]) -> ToolResult:
                    res = self.call_tool(s, o, args)
                    if not res.get("ok"):
                        return ToolResult(tool_name=n, ok=False, error=str(res.get("error") or "MCP tool failed"))
                    meta = {"images": list(res.get("images") or [])} if res.get("images") else {}
                    return ToolResult(tool_name=n, ok=True, output=str(res.get("output") or ""), metadata=meta)

                return _handler

            registry.register(
                ToolSpec(
                    name=namespaced,
                    description=spec.get("description") or f"MCP tool {orig} on {srv}",
                    schema=spec.get("schema") or {"type": "object", "properties": {}},
                    handler=_make_handler(srv, orig, namespaced),
                    read_only=False,
                    tier="write_local",
                    source=f"mcp:{srv}",
                )
            )
            count += 1
        return count

    def list_servers_health(self) -> list[dict[str, Any]]:
        return [h.to_dict() for h in self._health.values()]

    def reload(self, configs: Sequence[MCPServerConfig], *, registry: Any = None) -> list[dict[str, Any]]:
        """Hot-reload MCP connections & tools without restarting the host Gateway."""
        self.close()
        self._configs = {c.name: c for c in configs if c.enabled}
        self._health = {
            c.name: MCPServerHealth(name=c.name, transport=c.transport, connected=False)
            for c in self._configs.values()
        }
        self._discovered_tools = []
        if self._configs:
            if registry is not None:
                self.register_into_registry(registry)
            else:
                self.connect_all()
        return self.list_servers_health()

    def close(self) -> None:
        if self._loop is None:
            return

        async def _shutdown() -> None:
            for stack in list(self._stacks.values()):
                try:
                    await stack.aclose()
                except Exception:  # noqa: BLE001
                    pass
            self._stacks.clear()
            self._sessions.clear()

        try:
            self._run(_shutdown(), timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._loop = None
        self._thread = None


__all__ = [
    "LiveMCPManager",
    "MAX_MCP_IMAGE_BYTES",
    "MCPServerConfig",
    "MCPServerHealth",
    "extract_mcp_content",
    "load_mcp_server_configs",
    "remove_mcp_server_config",
    "save_mcp_server_config",
]
