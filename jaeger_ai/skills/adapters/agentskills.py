"""agentskills.io specification adapter.

agentskills.io is an open specification for agent skills (not a marketplace).
It defines a standard SKILL.md format that multiple platforms can implement.

Specification: https://agentskills.io/specification

Key features:
- Standard frontmatter format
- Skill discovery via skills.json
- Progressive disclosure (references/ directory)
- Optional: scripts/, templates/, tests/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import logging
import urllib.request
import urllib.error

from .base import SkillAdapter, ConversionResult, parse_frontmatter, format_frontmatter, slugify, compute_hash

logger = logging.getLogger(__name__)

AGENTS_SKILLS_REGISTRY = "https://agentskills.io"


@dataclass
class AgentSkill:
    """A skill from agentskills.io."""
    name: str
    description: str
    version: str
    author: str
    license: str
    repository: str
    tags: list[str]
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "repository": self.repository,
            "tags": self.tags,
        }


class AgentSkillsClient:
    """Client for agentskills.io registry."""

    def __init__(self, registry_url: str = AGENTS_SKILLS_REGISTRY):
        self.registry_url = registry_url.rstrip("/")

    def _request(self, endpoint: str, params: dict[str, str] | None = None) -> Any:
        """Make a request to the registry."""
        from urllib.parse import urlencode
        
        url = f"{self.registry_url}/{endpoint.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
        
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "JaegerAI-Skills-Adapter/1.0")
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error {e.code}: {e.reason}")
            raise
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise

    def search(self, query: str, *, limit: int = 20) -> list[AgentSkill]:
        """Search the agentskills.io registry."""
        try:
            data = self._request("api/skills/search", {"q": query, "limit": str(limit)})
            skills = []
            for item in data.get("skills", []):
                skills.append(AgentSkill(
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    version=item.get("version", "1.0.0"),
                    author=item.get("author", "unknown"),
                    license=item.get("license", "Unknown"),
                    repository=item.get("repository", ""),
                    tags=item.get("tags", []),
                ))
            return skills
        except Exception as e:
            logger.warning(f"agentskills.io search failed (may not be available): {e}")
            return []

    def get_skill(self, name: str) -> AgentSkill | None:
        """Get skill details from registry."""
        try:
            data = self._request(f"api/skills/{name}")
            return AgentSkill(
                name=data.get("name", name),
                description=data.get("description", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", "unknown"),
                license=data.get("license", "Unknown"),
                repository=data.get("repository", ""),
                tags=data.get("tags", []),
            )
        except Exception as e:
            logger.warning(f"Failed to get skill {name}: {e}")
            return None

    def download_skill(self, name: str, output_dir: Path) -> Path | None:
        """Download a skill from its repository."""
        skill = self.get_skill(name)
        if not skill or not skill.repository:
            return None
        
        output_dir.mkdir(parents=True, exist_ok=True)
        skill_dir = output_dir / slugify(name)
        
        import subprocess
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", skill.repository, str(skill_dir)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return skill_dir
        except Exception as e:
            logger.error(f"Failed to clone {skill.repository}: {e}")
        
        return None


class AgentSkillsAdapter(SkillAdapter):
    """Adapter for agentskills.io specification skills.

    agentskills.io is close to JROS format, so conversion is minimal.
    """

    source_format = "agentskills"

    def __init__(self):
        self.client = AgentSkillsClient()

    def _check_format(self, frontmatter: dict[str, Any]) -> bool:
        """Check if frontmatter follows agentskills.io spec."""
        # agentskills.io uses standard frontmatter without platform-specific metadata
        # Check for required fields
        return (
            "name" in frontmatter and
            "description" in frontmatter and
            "metadata" not in frontmatter  # No nested metadata = likely agentskills
        )

    def convert(self, source_path: Path, output_dir: Path | None = None) -> ConversionResult:
        """Convert an agentskills.io skill to JROS format."""
        skill_md_path = source_path / "SKILL.md" if source_path.is_dir() else source_path
        
        if not skill_md_path.exists():
            return ConversionResult(
                success=False,
                skill_name=source_path.name,
                source_format=self.source_format,
                errors=[f"SKILL.md not found at {skill_md_path}"],
            )

        try:
            content = skill_md_path.read_text(encoding="utf-8")
            agentskills_frontmatter, body = parse_frontmatter(content)
            
            skill_name = agentskills_frontmatter.get("name", skill_md_path.parent.name)
            slug = slugify(skill_name)
            
            # Extract metadata
            metadata = agentskills_frontmatter.get("metadata", {})
            
            # Build JROS frontmatter
            jros_frontmatter: dict[str, Any] = {
                "name": skill_name,
                "description": agentskills_frontmatter.get("description", ""),
                "license": agentskills_frontmatter.get("license", "Unknown"),
                "metadata": {
                    "jros": {
                        "version": agentskills_frontmatter.get("version", "1.0.0"),
                        "lifecycle": "imported",
                        "skill-class": "first-class",
                        "platforms": metadata.get("platforms", ["linux", "macos", "windows"]),
                        "requires-tools": self._extract_tools(agentskills_frontmatter),
                        "tags": metadata.get("tags", []),
                        "category": self._map_category(metadata.get("category", "other")),
                        "source": "agentskills.io",
                        "source_hash": compute_hash(content),
                    }
                }
            }
            
            # Format output
            jros_content = format_frontmatter(jros_frontmatter) + "\n\n" + body
            
            # Write output
            output_path = None
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                skill_dir = output_dir / slug
                skill_dir.mkdir(parents=True, exist_ok=True)
                
                output_path = skill_dir / "SKILL.md"
                output_path.write_text(jros_content, encoding="utf-8")
                
                # Copy additional files
                if source_path.is_dir():
                    import shutil
                    for item in source_path.iterdir():
                        if item.name != "SKILL.md" and item.is_dir():
                            dest = skill_dir / item.name
                            if not dest.exists():
                                shutil.copytree(item, dest)
                        elif item.is_file() and item.suffix in (".py", ".sh", ".json", ".yaml", ".yml"):
                            shutil.copy2(item, skill_dir)
            
            return ConversionResult(
                success=True,
                skill_name=skill_name,
                source_format=self.source_format,
                output_path=output_path,
                metadata={
                    "original_metadata": metadata,
                },
            )
            
        except Exception as e:
            logger.exception(f"Failed to convert agentskills.io skill {source_path}")
            return ConversionResult(
                success=False,
                skill_name=source_path.name,
                source_format=self.source_format,
                errors=[str(e)],
            )

    def install_from_registry(self, name: str, output_dir: Path) -> ConversionResult:
        """Download and install a skill from agentskills.io registry."""
        # Download
        skill_dir = self.client.download_skill(name, output_dir / "downloads")
        if not skill_dir:
            return ConversionResult(
                success=False,
                skill_name=name,
                source_format=self.source_format,
                errors=[f"Failed to download skill {name}"],
            )
        
        # Convert
        return self.convert(skill_dir, output_dir / "installed")


def install_from_agentskills(name: str, output_dir: Path) -> ConversionResult:
    """Convenience function to install a skill from agentskills.io."""
    adapter = AgentSkillsAdapter()
    return adapter.install_from_registry(name, output_dir)
