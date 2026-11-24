"""Fail-closed MCP tool policy, secret redaction, and safe naming."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any

SECRET_KEY_RE = re.compile(
    r"(authorization|cookie|token|secret|password|api[_-]?key|credential)",
    re.IGNORECASE,
)
MASK = "********"
ALLOWED_TOOL_POLICY_KEYS = frozenset({"include", "exclude", "read_only", "max", "gated"})


@dataclass(frozen=True)
class MCPToolPolicy:
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    read_only: tuple[str, ...] = ()
    max_tools: int = 0
    gated: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "MCPToolPolicy":
        data = raw if isinstance(raw, dict) else {}
        def _clean(key: str) -> tuple[str, ...]:
            vals = data.get(key)
            if not isinstance(vals, list):
                return ()
            return tuple(str(v).strip() for v in vals if isinstance(v, str) and str(v).strip())
        try:
            max_tools = max(0, int(data.get("max") or 0))
        except (TypeError, ValueError):
            max_tools = 0
        return cls(
            include=_clean("include"),
            exclude=_clean("exclude"),
            read_only=_clean("read_only"),
            max_tools=max_tools,
            gated=bool(data.get("gated", False)),
        )

    def matches_any(self, name: str, patterns: tuple[str, ...]) -> bool:
        return bool(name) and any(fnmatch.fnmatchcase(name, pat) for pat in patterns)

    def is_read_only(self, tool_name: str) -> bool:
        """Fail-closed: ONLY owner-declared read_only globs run without approval.

        Remote server annotations (readOnlyHint) are never trusted.
        """
        return self.matches_any(tool_name, self.read_only)

    def filter_tools(self, names: list[str]) -> list[str]:
        kept = [n for n in names if not self.include or self.matches_any(n, self.include)]
        kept = [n for n in kept if not self.matches_any(n, self.exclude)]
        if self.max_tools > 0:
            kept = kept[: self.max_tools]
        return kept

    def is_strictly_read_only_catalog(self, tool_names: list[str]) -> bool:
        return bool(tool_names) and all(self.is_read_only(n) for n in tool_names)


def agent_tool_name(server: str, tool: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{server}__{tool}")[:64]


def redact_secrets(value: Any, secrets: set[str]) -> Any:
    """Recursively scrub known credential strings from tool outputs/errors."""
    if not secrets:
        return value
    ordered = sorted((s for s in secrets if isinstance(s, str) and len(s) >= 4), key=len, reverse=True)
    if not ordered:
        return value

    def _scrub(node: Any) -> Any:
        if isinstance(node, str):
            out = node
            for s in ordered:
                out = out.replace(s, MASK)
            return out
        if isinstance(node, dict):
            return {k: _scrub(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_scrub(i) for i in node]
        if isinstance(node, tuple):
            return tuple(_scrub(i) for i in node)
        return node

    return _scrub(value)
