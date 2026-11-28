"""MCP schema byte budgets (Codex 8KB/64KB) & pooled server connections (OpenCode pattern)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

MAX_TOOL_SCHEMA_BYTES = 8 * 1024   # 8 KB per tool (Codex budget)
MAX_TOTAL_SCHEMA_BYTES = 64 * 1024  # 64 KB total across an MCP server / catalog


@dataclass(frozen=True)
class SchemaBudgetReport:
    accepted_count: int
    compacted_count: int
    dropped_tools: tuple[str, ...]
    total_bytes: int


def _schema_bytes(tool: Mapping[str, Any]) -> int:
    return len(json.dumps(tool, ensure_ascii=False, default=str).encode("utf-8"))


def _compact_tool_schema(tool: Mapping[str, Any], *, max_desc: int = 240) -> dict[str, Any]:
    """Strip bloated examples/defaults and trim verbose descriptions to fit budget."""
    out = dict(tool)
    desc = str(out.get("description") or "")
    if len(desc) > max_desc:
        out["description"] = desc[: max_desc - 3].rstrip() + "..."
    schema = out.get("input_schema") or out.get("inputSchema") or out.get("parameters")
    if isinstance(schema, dict):
        cleaned = _strip_verbose_schema_fields(schema)
        if "input_schema" in out:
            out["input_schema"] = cleaned
        elif "inputSchema" in out:
            out["inputSchema"] = cleaned
        elif "parameters" in out:
            out["parameters"] = cleaned
    return out


def _strip_verbose_schema_fields(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("examples", "$comment", "title"):
                continue
            if k == "description" and isinstance(v, str) and len(v) > 120:
                out[k] = v[:117].rstrip() + "..."
            else:
                out[k] = _strip_verbose_schema_fields(v)
        return out
    if isinstance(obj, list):
        return [_strip_verbose_schema_fields(item) for item in obj]
    return obj


def enforce_mcp_schema_budget(
    tools: Sequence[Mapping[str, Any]],
    *,
    max_per_tool: int = MAX_TOOL_SCHEMA_BYTES,
    max_total: int = MAX_TOTAL_SCHEMA_BYTES,
) -> tuple[list[dict[str, Any]], SchemaBudgetReport]:
    """Enforce Codex-style 8KB per-tool / 64KB total MCP schema byte budgets.

    Oversized tools are compacted first (stripping verbose descriptions/examples).
    Any tool still over ``max_per_tool`` or pushing the cumulative size past
    ``max_total`` is dropped and reported in ``SchemaBudgetReport.dropped_tools``.
    """
    accepted: list[dict[str, Any]] = []
    dropped: list[str] = []
    compacted_count = 0
    total_bytes = 0

    for raw in tools:
        item = dict(raw)
        name = str(item.get("name") or item.get("tool_name") or "unknown")
        size = _schema_bytes(item)
        if size > max_per_tool:
            item = _compact_tool_schema(item)
            compacted_count += 1
            size = _schema_bytes(item)
        if size > max_per_tool or (total_bytes + size) > max_total:
            dropped.append(name)
            continue
        accepted.append(item)
        total_bytes += size

    return accepted, SchemaBudgetReport(
        accepted_count=len(accepted),
        compacted_count=compacted_count,
        dropped_tools=tuple(dropped),
        total_bytes=total_bytes,
    )


@dataclass
class PooledConnection:
    server_name: str
    handle: Any
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)


class MCPConnectionPool:
    """Thread-safe pooled MCP client connections with idle eviction (OpenCode pattern)."""

    def __init__(
        self,
        *,
        idle_ttl_s: float = 300.0,
        closer: Callable[[Any], None] | None = None,
    ) -> None:
        self._idle_ttl_s = max(1.0, float(idle_ttl_s))
        self._closer = closer
        self._lock = threading.RLock()
        self._pool: dict[str, PooledConnection] = {}

    def acquire(
        self,
        server_name: str,
        factory: Callable[[], Any],
        *,
        is_alive: Callable[[Any], bool] | None = None,
    ) -> Any:
        now = time.monotonic()
        with self._lock:
            existing = self._pool.get(server_name)
            if existing is not None:
                expired = (now - existing.last_used_at) > self._idle_ttl_s
                alive = True if is_alive is None else bool(is_alive(existing.handle))
                if not expired and alive:
                    existing.last_used_at = now
                    return existing.handle
                self._close_handle(existing.handle)
                self._pool.pop(server_name, None)

            handle = factory()
            self._pool[server_name] = PooledConnection(
                server_name=server_name,
                handle=handle,
                created_at=now,
                last_used_at=now,
            )
            return handle

    def evict_idle(self, *, now: float | None = None) -> list[str]:
        current = time.monotonic() if now is None else now
        evicted: list[str] = []
        with self._lock:
            for name, conn in list(self._pool.items()):
                if (current - conn.last_used_at) > self._idle_ttl_s:
                    self._close_handle(conn.handle)
                    del self._pool[name]
                    evicted.append(name)
        return evicted

    def release(self, server_name: str) -> bool:
        with self._lock:
            conn = self._pool.pop(server_name, None)
            if conn is None:
                return False
            self._close_handle(conn.handle)
            return True

    def close_all(self) -> int:
        with self._lock:
            count = len(self._pool)
            for conn in list(self._pool.values()):
                self._close_handle(conn.handle)
            self._pool.clear()
            return count

    def active_servers(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._pool.keys()))

    def _close_handle(self, handle: Any) -> None:
        if self._closer is not None:
            try:
                self._closer(handle)
                return
            except Exception:  # noqa: BLE001
                return
        close_fn = getattr(handle, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:  # noqa: BLE001
                pass


__all__ = [
    "MAX_TOOL_SCHEMA_BYTES",
    "MAX_TOTAL_SCHEMA_BYTES",
    "MCPConnectionPool",
    "PooledConnection",
    "SchemaBudgetReport",
    "enforce_mcp_schema_budget",
]
