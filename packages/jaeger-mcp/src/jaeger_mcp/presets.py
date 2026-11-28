"""First-class ecosystem MCP server presets (Aether Studio, REA, and extensible local tools)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .client import MCPServerConfig


@dataclass(frozen=True)
class MCPServerPreset:
    preset_id: str
    name: str
    title: str
    description: str
    transport: str  # "streamable_http" | "stdio" | "sse"
    default_url: str = ""
    default_command: str = ""
    default_args: tuple[str, ...] = ()
    requires_token: bool = False
    token_label: str = "Bearer Token (optional)"
    category: str = "ecosystem"

    def to_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "transport": self.transport,
            "default_url": self.default_url,
            "default_command": self.default_command,
            "default_args": list(self.default_args),
            "requires_token": self.requires_token,
            "token_label": self.token_label,
            "category": self.category,
        }


BUILTIN_MCP_PRESETS: tuple[MCPServerPreset, ...] = (
    MCPServerPreset(
        preset_id="aether_studio",
        name="aether_studio",
        title="Aether Studio & Aether-CAD",
        description="Connects Jaeger to your local Aether Studio host (:8780) for parametric CAD parts, assemblies, verification, and viewport PNG inspection.",
        transport="streamable_http",
        default_url="http://127.0.0.1:8780/mcp",
        requires_token=False,
        token_label="Studio Agent Connection Bearer Token",
        category="jenkins_robotics",
    ),
    MCPServerPreset(
        preset_id="jaeger_arena",
        name="jaeger_arena",
        title="Jaeger Arena (Training & Challenges)",
        description="Connects Jaeger to your local Jaeger Arena server (:8792) for skill-tree worlds, practice challenges, and verified XP progression.",
        transport="streamable_http",
        default_url="http://127.0.0.1:8792/mcp/",
        requires_token=True,
        token_label="Arena Participant Bearer Token",
        category="jenkins_robotics",
    ),
    MCPServerPreset(
        preset_id="rea",
        name="rea",
        title="REA (Reverse Engineer Anything)",
        description="Bridges Jaeger to Ghidra, Hopper, JADX, Electron, and APK binary analysis via the MIT REA MCP server.",
        transport="stdio",
        default_command="npx",
        default_args=("-y", "rea-agents", "mcp"),
        requires_token=False,
        category="reverse_engineering",
    ),
)

_PRESETS_BY_ID: dict[str, MCPServerPreset] = {p.preset_id: p for p in BUILTIN_MCP_PRESETS}


def list_mcp_presets() -> list[dict[str, Any]]:
    return [p.to_dict() for p in BUILTIN_MCP_PRESETS]


def build_preset_config(
    preset_id: str,
    *,
    url: str | None = None,
    bearer_token: str | None = None,
    command: str | None = None,
    args: list[str] | tuple[str, ...] | None = None,
    headers: Mapping[str, str] | None = None,
    name: str | None = None,
    timeout_s: float = 30.0,
) -> MCPServerConfig:
    """Build a ready-to-save MCPServerConfig from a built-in ecosystem preset."""
    pid = str(preset_id or "").strip().lower()
    preset = _PRESETS_BY_ID.get(pid)
    if preset is None:
        raise KeyError(f"Unknown MCP preset: {preset_id!r}. Available: {', '.join(_PRESETS_BY_ID)}")

    merged_headers: dict[str, str] = {str(k): str(v) for k, v in (headers or {}).items()}
    tok = str(bearer_token or "").strip()
    if tok:
        merged_headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"

    return MCPServerConfig(
        name=str(name or preset.name).strip() or preset.name,
        transport=preset.transport,
        url=str(url if url is not None else preset.default_url).strip(),
        command=str(command if command is not None else preset.default_command).strip(),
        args=tuple(str(a) for a in (args if args is not None else preset.default_args)),
        headers=merged_headers,
        timeout_s=float(timeout_s or 30.0),
        enabled=True,
    )


__all__ = [
    "BUILTIN_MCP_PRESETS",
    "MCPServerPreset",
    "build_preset_config",
    "list_mcp_presets",
]
