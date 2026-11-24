"""Locked, discovery-only disk cache for MCP tool metadata.

Architectural boundary (JOMA v1.1 §4.2):
- Stores DISCOVERY METADATA ONLY (tool names, descriptions, input schemas).
- NEVER caches authorization decisions, ``read_only`` trust grants, or confirmed
  live availability. Gateway remains the sole owner of tool enablement,
  approvals, registration, and lifecycle.
- Any call to a lazily discovered tool MUST connect and reconcile live server
  schemas before dispatch.
- Every read-modify-write is serialized by BOTH a process-local threading lock
  and an interprocess ``fcntl.flock`` lockfile.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover — non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

DEFAULT_MCP_PROTOCOL_VERSION = "2024-11-05"
_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PROCESS_LOCKS[key] = lock
        return lock


@dataclass(frozen=True)
class CachedToolEntry:
    """Discovery metadata only — intentionally omits authorization/read_only fields."""

    server_name: str
    tool_name: str
    agent_name: str
    description: str
    input_schema: dict[str, Any]


def _executable_fingerprint(command: str | None, args: list[Any] | None) -> str:
    """Best-effort local revision fingerprint (mtime_ns + size) for command & script arg."""
    parts: list[str] = []
    candidates: list[str] = []
    if command:
        resolved = shutil.which(command) or command
        candidates.append(resolved)
    for arg in (args or [])[:3]:
        if isinstance(arg, str) and ("/" in arg or arg.endswith((".py", ".js", ".mjs", ".sh"))):
            candidates.append(arg)
    for raw in candidates:
        try:
            st = os.stat(raw)
            parts.append(f"{raw}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{raw}:missing")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16] if parts else ""


def _safe_mapping_fingerprint(mapping: Any) -> list[str]:
    """Capture key names and secret_ref identifiers without ever hashing raw secret values."""
    if not isinstance(mapping, dict):
        return []
    out: list[str] = []
    for key in sorted(str(k) for k in mapping):
        val = mapping.get(key)
        if isinstance(val, dict) and set(val) == {"secret_ref"}:
            out.append(f"{key}:ref:{val['secret_ref']}")
        else:
            out.append(f"{key}:present")
    return out


class MCPSchemaCache:
    """Thread-safe and interprocess-locked discovery-only MCP tool metadata cache."""

    def __init__(self, path: Path, *, default_ttl_s: float = 86_400.0) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.default_ttl_s = max(0.0, float(default_ttl_s))

    @staticmethod
    def config_digest(
        server_entry: dict[str, Any],
        *,
        protocol_version: str = DEFAULT_MCP_PROTOCOL_VERSION,
        package_revision: str = "",
    ) -> str:
        """Hash config, filter policy, transport security, env/cred refs, sandbox,
        protocol version, and executable/package revision — never raw secrets."""
        tools_raw = server_entry.get("tools") if isinstance(server_entry.get("tools"), dict) else {}
        structural = {
            "name": server_entry.get("name"),
            "command": server_entry.get("command"),
            "args": list(server_entry.get("args") or []),
            "url": server_entry.get("url"),
            "auth": server_entry.get("auth") or "",
            "scope": server_entry.get("scope") or "",
            "sandbox": server_entry.get("sandbox") or "",
            "env_refs": _safe_mapping_fingerprint(server_entry.get("env")),
            "header_refs": _safe_mapping_fingerprint(server_entry.get("headers")),
            "tools_filter": {
                "include": list(tools_raw.get("include") or []),
                "exclude": list(tools_raw.get("exclude") or []),
                "max": tools_raw.get("max") or 0,
                "gated": bool(tools_raw.get("gated", False)),
            },
            "protocol_version": protocol_version,
            "executable_fingerprint": _executable_fingerprint(
                server_entry.get("command"),
                server_entry.get("args"),
            ),
            "package_revision": package_revision,
        }
        return hashlib.sha256(json.dumps(structural, sort_keys=True).encode("utf-8")).hexdigest()[:32]

    @contextlib.contextmanager
    def _locked(self, *, exclusive: bool) -> Iterator[None]:
        tlock = _thread_lock_for(self.lock_path)
        with tlock:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                yield
            finally:
                try:
                    if fcntl is not None:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _read_all_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 2, "discovery_only": True, "servers": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("servers"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"version": 2, "discovery_only": True, "servers": {}}

    def _write_all_unlocked(self, data: dict[str, Any]) -> None:
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
        with self._locked(exclusive=False):
            data = self._read_all_unlocked()
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
        with self._locked(exclusive=True):
            data = self._read_all_unlocked()
            data["version"] = 2
            data["discovery_only"] = True
            data["servers"][server_name] = {
                "digest": digest,
                "cached_at": time.time() if now is None else now,
                "tools": [
                    {
                        "tool_name": t.tool_name,
                        "agent_name": t.agent_name,
                        "description": t.description,
                        "input_schema": t.input_schema,
                    }
                    for t in tools
                ],
            }
            self._write_all_unlocked(data)

    def invalidate(self, server_name: str) -> bool:
        with self._locked(exclusive=True):
            data = self._read_all_unlocked()
            if server_name not in data["servers"]:
                return False
            del data["servers"][server_name]
            self._write_all_unlocked(data)
            return True

    def invalidate_all(self) -> None:
        with self._locked(exclusive=True):
            data = self._read_all_unlocked()
            if not data["servers"]:
                return
            data["servers"] = {}
            self._write_all_unlocked(data)
