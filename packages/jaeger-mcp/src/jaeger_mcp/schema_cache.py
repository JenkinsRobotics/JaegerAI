"""Persistent disk tool-schema cache for lazy MCP discovery (opencode/cline pattern).

Caches discovered MCP server tool catalogs keyed by server config digest so
tool_search and UI inventory work in 0ms without eagerly spawning heavy stdio
servers (e.g. Node/Ghidra) until a tool from that server is actually invoked.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CachedToolEntry:
    server_name: str
    tool_name: str
    agent_name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False


class MCPSchemaCache:
    """Thread-safe atomic JSON cache of MCP tool schemas on disk."""

    def __init__(self, path: Path, *, default_ttl_s: float = 86_400.0) -> None:
        self.path = Path(path)
        self.default_ttl_s = max(0.0, float(default_ttl_s))

    @staticmethod
    def config_digest(server_entry: dict[str, Any]) -> str:
        """Hash non-secret structural fields so config changes invalidate cache."""
        structural = {
            "name": server_entry.get("name"),
            "command": server_entry.get("command"),
            "args": server_entry.get("args") or [],
            "url": server_entry.get("url"),
            "tools": server_entry.get("tools") or {},
        }
        return hashlib.sha256(json.dumps(structural, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "servers": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("servers"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 1, "servers": {}}

    def _write_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".mcp-cache-", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def get(
        self,
        server_name: str,
        *,
        expected_digest: str | None = None,
        now: float | None = None,
    ) -> list[CachedToolEntry] | None:
        data = self._read_all()
        row = data["servers"].get(server_name)
        if not isinstance(row, dict):
            return None
        if expected_digest and row.get("digest") != expected_digest:
            return None
        ts = float(row.get("cached_at") or 0.0)
        current = time.time() if now is None else now
        if self.default_ttl_s > 0 and (current - ts) > self.default_ttl_s:
            return None
        out: list[CachedToolEntry] = []
        for item in row.get("tools") or []:
            if not isinstance(item, dict) or not item.get("tool_name"):
                continue
            out.append(CachedToolEntry(
                server_name=server_name,
                tool_name=str(item["tool_name"]),
                agent_name=str(item.get("agent_name") or ""),
                description=str(item.get("description") or ""),
                input_schema=dict(item.get("input_schema") or {}),
                read_only=bool(item.get("read_only", False)),
            ))
        return out

    def put(
        self,
        server_name: str,
        digest: str,
        tools: list[CachedToolEntry],
        *,
        now: float | None = None,
    ) -> None:
        data = self._read_all()
        data["servers"][server_name] = {
            "digest": digest,
            "cached_at": time.time() if now is None else now,
            "tools": [
                {
                    "tool_name": t.tool_name,
                    "agent_name": t.agent_name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    "read_only": t.read_only,
                }
                for t in tools
            ],
        }
        self._write_all(data)

    def invalidate(self, server_name: str) -> bool:
        data = self._read_all()
        if server_name not in data["servers"]:
            return False
        del data["servers"][server_name]
        self._write_all(data)
        return True
