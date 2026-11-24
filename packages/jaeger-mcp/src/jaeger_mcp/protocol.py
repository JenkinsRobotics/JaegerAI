"""MCP Prompts, Workspace Roots, and safe Read-Only ReconnectPolicy."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote


@dataclass(frozen=True)
class MCPPromptSpec:
    server_name: str
    name: str
    description: str = ""
    arguments: tuple[dict[str, Any], ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"mcp:{self.server_name}/prompt/{self.name}"


def build_roots_payload(paths: list[str | Path]) -> list[dict[str, str]]:
    """Build spec-compliant MCP ``roots/list`` entries (``file://`` URIs)."""
    roots: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw).expanduser().resolve()
        uri = "file://" + quote(str(p), safe="/:@-._~")
        if uri in seen:
            continue
        seen.add(uri)
        roots.append({"uri": uri, "name": p.name or str(p)})
    return roots


@dataclass
class ReconnectPolicy:
    """Bounded exponential backoff reconnect policy — STRICTLY read-only servers only.

    Mutating MCP servers stay fail-closed on ``outcome_unknown`` so an interrupted
    write is never silently replayed; strictly read-only servers (e.g. read-only
    GitHub, docs, search) can safely reconnect with backoff on a broken pipe.
    """

    max_attempts: int = 3
    base_delay_s: float = 0.5
    max_delay_s: float = 8.0
    _attempts: dict[str, int] = field(default_factory=dict)
    _last_attempt_at: dict[str, float] = field(default_factory=dict)

    def can_auto_reconnect(self, server_name: str, *, strictly_read_only: bool) -> bool:
        if not strictly_read_only:
            return False
        return self._attempts.get(server_name, 0) < self.max_attempts

    def next_delay(self, server_name: str, *, now: float | None = None) -> float:
        attempt = self._attempts.get(server_name, 0)
        self._attempts[server_name] = attempt + 1
        self._last_attempt_at[server_name] = time.monotonic() if now is None else now
        return min(self.max_delay_s, self.base_delay_s * (2 ** attempt))

    def record_success(self, server_name: str) -> None:
        self._attempts.pop(server_name, None)
        self._last_attempt_at.pop(server_name, None)
