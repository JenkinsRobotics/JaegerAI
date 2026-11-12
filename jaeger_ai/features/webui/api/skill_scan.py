"""Local SKILL.md scanning helpers for the WebUI skills endpoints.

The skills routes were ported from hermes-webui, which imported these from the
hermes ``agent.skill_utils`` / ``tools.skills_tool`` modules. Those packages are
not part of Jaeger, so /api/skills raised ModuleNotFoundError; this module is
the self-contained replacement (frontmatter parsing reuses the playbook
registry's YAML parser so both surfaces read SKILL.md the same way).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Iterator

EXCLUDED_SKILL_DIRS = frozenset({".git", ".github", ".hub", "node_modules", "__pycache__", ".venv"})

_PLATFORMS = {"mac": "macos", "macos": "macos", "osx": "macos", "darwin": "macos",
              "linux": "linux", "win": "windows", "windows": "windows"}


def iter_skill_index_files(root: Path, filename: str = "SKILL.md") -> Iterator[Path]:
    """Yield every ``filename`` under ``root`` (sorted, excluded dirs pruned)."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_SKILL_DIRS)
        if filename in filenames:
            yield Path(dirpath) / filename


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split a leading ``---`` YAML block from the body. ``({}, content)`` if absent."""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            try:
                import yaml
                data = yaml.safe_load(content[3:end])
            except Exception:  # noqa: BLE001 - malformed frontmatter means none
                data = None
            body = content[end + 4:].split("\n", 1)[1] if "\n" in content[end + 4:] else ""
            return (data if isinstance(data, dict) else {}), body
    return {}, content


def parse_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        value = value.strip().strip("[]").split(",")
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v).strip().strip("'\"") for v in value if str(v).strip().strip("'\"")]


def skill_matches_platform(frontmatter: dict[str, Any]) -> bool:
    declared = frontmatter.get("platforms")
    if not declared:
        return True
    names = {_PLATFORMS.get(str(p).strip().lower()) for p in parse_tags(declared)}
    here = "macos" if sys.platform == "darwin" else "windows" if sys.platform.startswith("win") else "linux"
    return here in names


