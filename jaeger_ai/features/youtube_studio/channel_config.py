"""YouTube channel configuration — makes the studio universal.

Loads channel-specific settings from ``~/.jaeger/instances/<name>/youtube.toml``
or falls back to generic defaults. Nothing here is hardcoded to a specific person
or channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChannelConfig:
    """Configuration for a YouTube channel's content pipeline."""

    # Channel identity
    channel_name: str = "Your Channel Name"
    channel_description: str = "A build show about making things with local AI, 3D printing, and CNC"

    # On-screen cast
    host_description: str = "an AI host that presents, explains and narrates"
    robot_description: str = "a robot co-host with short, dry, practical lines"

    # Content rules (what NOT to show)
    privacy_rules: str = (
        "This is a build show, not a personal show: never mention age, family, "
        "parents, relationships, marriage, finances beyond the project budget, "
        "or location beyond 'the workshop'. Never invent costs, measurements "
        "or test results: if a number is not in the brief or build logs, write [TBD]."
    )

    # Project info
    project_name: str = "Your Project"
    project_description: str = (
        "a habitat-in-a-box living and robotics workshop built on a "
        "small budget with local AI, 3D printing and CNC"
    )

    # Section headers
    open_questions_header: str = "Open questions for the operator"

    # Extra context (optional)
    extra_context: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelConfig":
        """Build from a config dict, ignoring unknown keys."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def build_system_prompt(self) -> str:
        """Generate the system prompt from this configuration."""
        return f"""\
You write episodes for the YouTube channel "{self.channel_name}", {self.channel_description}.

On-screen cast:
- HOST: {self.host_description}.
- ROBOT: {self.robot_description}.
{self.extra_context}
{self.privacy_rules}

Return markdown with exactly these sections, in this order:
# <Episode title>
## Hook (0:00-0:30)
## Outline
(numbered beats with rough timestamps)
## Shot list
(markdown table: | # | Shot | Source | Notes | where Source is one of
BUILD FOOTAGE, AI HOST, ROBOT, SCREEN, B-ROLL)
## Narration
(one spoken line per paragraph, each starting with "HOST:" or "ROBOT:")
## {self.open_questions_header}
"""


def load_channel_config(instance_dir: Path | None = None) -> ChannelConfig:
    """Load channel configuration from instance directory or use defaults.

    Looks for ``youtube.toml`` in the instance directory. Falls back to
    generic defaults if the file is missing or invalid.
    """
    if instance_dir is None:
        instance_dir = Path.home() / ".jaeger" / "instances" / "jaeger"

    config_path = instance_dir / "youtube.toml"
    if not config_path.exists():
        return ChannelConfig()

    try:
        import tomllib
        with config_path.open("rb") as f:
            data = tomllib.load(f)
        # Support both flat and [channel] section formats
        channel_data = data.get("channel", data)
        return ChannelConfig.from_dict(channel_data)
    except (OSError, ImportError, ValueError):
        # Invalid config — use defaults
        return ChannelConfig()


__all__ = ["ChannelConfig", "load_channel_config"]
