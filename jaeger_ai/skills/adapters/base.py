"""Base classes for skill adapters.

All skill adapters convert external skill formats to JaegerAI's JROS skill format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import hashlib
import re


@dataclass
class ConversionResult:
    """Result of converting a skill."""
    success: bool
    skill_name: str
    source_format: str
    target_format: str = "jros.skill/v1"
    output_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "skill_name": self.skill_name,
            "source_format": self.source_format,
            "target_format": self.target_format,
            "output_path": str(self.output_path) if self.output_path else None,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
        }


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_content).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_text = parts[1].strip()
    body = parts[2].strip() if len(parts) > 2 else ""

    # Simple YAML parser (no external dependency needed for basic cases)
    frontmatter: dict[str, Any] = {}
    current_key: str | None = None
    current_value: Any = None
    current_list: list[str] | None = None

    for line in frontmatter_text.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue

        # List item
        if line.strip().startswith("- "):
            if current_list is not None:
                current_list.append(line.strip()[2:].strip().strip("'\""))
            continue

        # Key-value pair
        if ":" in line:
            # Save previous value
            if current_key is not None:
                if current_list is not None:
                    frontmatter[current_key] = current_list
                    current_list = None
                elif current_value is not None:
                    frontmatter[current_key] = current_value
                current_value = None

            key, _, value = line.partition(":")
            current_key = key.strip()
            value = value.strip()

            # Empty value - might be a list or nested dict
            if not value:
                current_value = None
                current_list = []
            # Quoted string
            elif value.startswith("'") or value.startswith('"'):
                current_value = value.strip("'\"")
            # Array inline [a, b, c]
            elif value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
                frontmatter[current_key] = items
                current_key = None
            # Boolean
            elif value.lower() in ("true", "yes"):
                current_value = True
            elif value.lower() in ("false", "no"):
                current_value = False
            # Number
            elif value.replace(".", "").replace("-", "").isdigit():
                current_value = float(value) if "." in value else int(value)
            # Plain string
            else:
                current_value = value

    # Save last value
    if current_key is not None:
        if current_list is not None:
            frontmatter[current_key] = current_list
        elif current_value is not None:
            frontmatter[current_key] = current_value

    return frontmatter, body


def format_frontmatter(frontmatter: dict[str, Any]) -> str:
    """Format a dict as YAML frontmatter."""
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for subkey, subvalue in value.items():
                lines.append(f"  {subkey}: {_format_value(subvalue)}")
        elif isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {_format_value(value)}")
    lines.append("---")
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    """Format a value for YAML output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, str):
        # Quote if contains special chars
        if any(c in value for c in [":", "#", "[", "]", "{", "}", "\n"]):
            return f'"{value}"'
        return value
    elif value is None:
        return ""
    return str(value)


def slugify(name: str) -> str:
    """Convert a skill name to a slug."""
    slug = re.sub(r"[^a-zA-Z0-9\-_/ ]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


def compute_hash(content: str) -> str:
    """Compute SHA256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class SkillAdapter:
    """Base class for skill adapters.

    Subclasses implement conversion from external skill formats to JROS format.
    """

    source_format: str = "unknown"

    def convert(self, source_path: Path, output_dir: Path | None = None) -> ConversionResult:
        """Convert a skill from source format to JROS format.

        Args:
            source_path: Path to the source skill (directory or SKILL.md file)
            output_dir: Where to write the converted skill (optional)

        Returns:
            ConversionResult with success status and details
        """
        raise NotImplementedError

    def detect_format(self, path: Path) -> bool:
        """Check if this adapter can handle the given path."""
        skill_md = path / "SKILL.md" if path.is_dir() else path
        if not skill_md.exists():
            return False

        try:
            content = skill_md.read_text(encoding="utf-8")
            frontmatter, _ = parse_frontmatter(content)
            return self._check_format(frontmatter)
        except Exception:
            return False

    def _check_format(self, frontmatter: dict[str, Any]) -> bool:
        """Check if frontmatter matches this adapter's format."""
        return False

    def _map_category(self, source_category: str) -> str:
        """Map source category to JROS category."""
        category_map = {
            # Hermes categories
            "creative": "creative",
            "communication": "communication",
            "devops": "devops",
            "productivity": "productivity",
            "research": "research",
            "security": "security",
            "smart-home": "smart-home",
            "software-development": "software-development",
            # OpenClaw categories
            "web": "productivity",
            "media": "media",
            "messaging": "communication",
            "home-automation": "smart-home",
            # Default
            "other": "imported",
        }
        return category_map.get(source_category.lower(), "imported")

    def _extract_tools(self, frontmatter: dict[str, Any]) -> list[str]:
        """Extract required tools from frontmatter."""
        tools = []

        # Hermes format
        hermes_meta = frontmatter.get("metadata", {}).get("hermes", {})
        if "requirements" in hermes_meta:
            tools.extend(hermes_meta["requirements"].get("tools", []))

        # OpenClaw format
        openclaw_meta = frontmatter.get("metadata", {}).get("openclaw", {})
        if "requires" in openclaw_meta:
            tools.extend(openclaw_meta["requires"].get("bins", []))

        # Top-level
        if "requires" in frontmatter:
            tools.extend(frontmatter["requires"].get("tools", []))
            tools.extend(frontmatter["requires"].get("bins", []))

        return list(dict.fromkeys(tools))  # Dedupe, preserve order
