"""Operator configuration — universal, per-instance settings.

Loads operator-specific configuration from ``~/.jaeger/operator.toml`` or
instance config (``~/.jaeger/instances/<name>/operator.toml``). All personal
preferences are configurable; nothing is hardcoded to a specific person.

Configuration cascade (later overrides earlier):
1. Built-in defaults (this module)
2. Global operator config: ``~/.jaeger/operator.toml``
3. Instance config: ``~/.jaeger/instances/<name>/operator.toml``
4. OS account detection (host_context.operator_name)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .host_context import operator_name as detect_operator_name


@dataclass(frozen=True)
class OperatorConfig:
    """Operator-specific configuration — all personal preferences."""

    # Identity
    name: str | None = None  # Display name; falls back to OS account detection
    email: str | None = None  # Contact email (optional)

    # Business / projects
    business_name: str = "Your Business"
    project_root: str | None = None  # Root directory for projects
    nas_path: str | None = None  # NAS mount path (e.g., /Volumes/MyNAS)

    # Content / channels
    youtube_channel_name: str = "Your Channel Name"
    youtube_channel_handle: str | None = None  # @handle

    # Preferences
    timezone: str = "UTC"
    language: str = "en"

    # Custom lists (never hardcoded)
    never_list: tuple[str, ...] = field(default_factory=tuple)  # Email sender NEVER list
    allowed_paths: tuple[str, ...] = field(default_factory=tuple)  # Extra allowed paths for tools

    # Notification preferences
    ntfy_url: str | None = None  # Self-hosted ntfy topic URL
    ntfy_token: str | None = None  # ntfy auth token (never logged)

    # Voice preferences
    wake_word: str | None = None  # Custom wake word (e.g., "jarvis")
    voice_enabled: bool = True

    # Extra context for prompts (user-defined)
    custom_context: str = ""  # Added to system prompt context

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperatorConfig":
        """Build from a config dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        # Convert lists to tuples for frozen dataclass
        for key in ("never_list", "allowed_paths"):
            if key in filtered and isinstance(filtered[key], list):
                filtered[key] = tuple(filtered[key])
        return cls(**filtered)

    @property
    def display_name(self) -> str:
        """Name to use in prompts and greetings."""
        return self.name or detect_operator_name() or "the operator"

    def to_prompt_context(self) -> str:
        """Generate context block for system prompts."""
        lines = []
        if self.business_name and self.business_name != "Your Business":
            lines.append(f"Business: {self.business_name}")
        if self.project_root:
            lines.append(f"Project root: {self.project_root}")
        if self.nas_path:
            lines.append(f"NAS: {self.nas_path}")
        if self.youtube_channel_name and self.youtube_channel_name != "Your Channel Name":
            lines.append(f"YouTube channel: {self.youtube_channel_name}")
        if self.custom_context:
            lines.append(f"Additional context: {self.custom_context}")
        return "\n".join(lines) if lines else ""


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning empty dict on any error."""
    if not path.exists():
        return {}
    try:
        import tomllib
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, ImportError, ValueError):
        return {}


def load_operator_config(instance_name: str = "jaeger") -> OperatorConfig:
    """Load operator configuration with full cascade.

    Args:
        instance_name: Instance name (default: "jaeger")

    Returns:
        OperatorConfig with merged settings from all sources.
    """
    # Start with defaults
    data: dict[str, Any] = {}

    # 1. Global operator config
    global_path = Path.home() / ".jaeger" / "operator.toml"
    global_data = _load_toml(global_path)
    if "operator" in global_data:
        data.update(global_data["operator"])
    else:
        data.update(global_data)

    # 2. Instance-specific overrides
    instance_path = Path.home() / ".jaeger" / "instances" / instance_name / "operator.toml"
    instance_data = _load_toml(instance_path)
    if "operator" in instance_data:
        data.update(instance_data["operator"])
    else:
        data.update(instance_data)

    # 3. Environment variable overrides (highest priority for secrets)
    env_overrides: dict[str, Any] = {}
    if os.environ.get("JAEGER_OPERATOR_NAME"):
        env_overrides["name"] = os.environ["JAEGER_OPERATOR_NAME"]
    if os.environ.get("JAEGER_NTFY_URL"):
        env_overrides["ntfy_url"] = os.environ["JAEGER_NTFY_URL"]
    if os.environ.get("JAEGER_NTFY_TOKEN"):
        env_overrides["ntfy_token"] = os.environ["JAEGER_NTFY_TOKEN"]
    if os.environ.get("JAEGER_WAKE_WORD"):
        env_overrides["wake_word"] = os.environ["JAEGER_WAKE_WORD"]
    data.update(env_overrides)

    return OperatorConfig.from_dict(data)


def write_default_config(path: Path | None = None, *, force: bool = False) -> Path:
    """Write a default operator.toml template for the user to customize.

    Args:
        path: Where to write (default: ~/.jaeger/operator.toml)
        force: Overwrite existing file

    Returns:
        Path where config was written.
    """
    if path is None:
        path = Path.home() / ".jaeger" / "operator.toml"

    if path.exists() and not force:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    template = """\
# JaegerAI Operator Configuration
# ==============================
# Personal settings for your JaegerAI instance.
# Delete any line to use the default. All values are optional.

[operator]
# Your name (defaults to OS account name)
# name = "Alex"

# Contact email (optional)
# email = "alex@example.com"

# Business / organization name
# business_name = "My Company"

# Paths
# project_root = "/Users/alex/projects"
# nas_path = "/Volumes/MyNAS"

# YouTube channel (for content automation)
# youtube_channel_name = "My Build Channel"
# youtube_channel_handle = "@mybuildchannel"

# Preferences
# timezone = "America/Los_Angeles"
# language = "en"

# Email NEVER list — senders to never auto-process
# never_list = ["spam@example.com", "newsletter@example.com"]

# Extra paths tools are allowed to access (beyond defaults)
# allowed_paths = ["/Users/alex/special-project"]

# Notifications (ntfy self-hosted over Tailscale)
# ntfy_url = "https://your-host.ts.net:8443/ntfy/jaeger"
# ntfy_token = "tk_your_token_here"  # Never logged

# Voice
# wake_word = "jarvis"  # Custom wake word
# voice_enabled = true

# Custom context added to system prompts
# custom_context = "I work on robotics projects. I prefer concise answers."
"""
    path.write_text(template, encoding="utf-8")
    path.chmod(0o600)  # Config may contain tokens
    return path


__all__ = [
    "OperatorConfig",
    "load_operator_config",
    "write_default_config",
]
