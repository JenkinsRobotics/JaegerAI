"""Hermes Agent skill adapter.

Converts Hermes Agent SKILL.md format to JaegerAI JROS skill format.

Hermes format:
```yaml
---
name: skill-name
version: 1.0.0
description: "..."
license: MIT
metadata:
  hermes:
    tags: [tag1, tag2]
    category: category-name
    fallback_for_toolsets: [toolset1]
    requirements:
      tools: [tool1, tool2]
      env: [VAR1]
      bins: [bin1]
---

# Skill Title

## Instructions
...
```
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import logging
import shutil

from .base import SkillAdapter, ConversionResult, parse_frontmatter, format_frontmatter, slugify, compute_hash

logger = logging.getLogger(__name__)


class HermesSkillAdapter(SkillAdapter):
    """Adapter for Hermes Agent skills."""

    source_format = "hermes"

    def _check_format(self, frontmatter: dict[str, Any]) -> bool:
        """Check if frontmatter is Hermes format."""
        metadata = frontmatter.get("metadata", {})
        return "hermes" in metadata

    def convert(self, source_path: Path, output_dir: Path | None = None) -> ConversionResult:
        """Convert a Hermes skill to JROS format."""
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
            hermes_frontmatter, body = parse_frontmatter(content)
            
            # Extract Hermes metadata
            hermes_meta = hermes_frontmatter.get("metadata", {}).get("hermes", {})
            
            skill_name = hermes_frontmatter.get("name", skill_md_path.parent.name)
            slug = slugify(skill_name)
            
            warnings = []
            
            # Build JROS frontmatter
            jros_frontmatter: dict[str, Any] = {
                "name": skill_name,
                "description": hermes_frontmatter.get("description", ""),
                "license": hermes_frontmatter.get("license", "Unknown"),
                "metadata": {
                    "jros": {
                        "version": hermes_frontmatter.get("version", "1.0.0"),
                        "lifecycle": "imported",
                        "skill-class": "first-class",
                        "platforms": self._detect_platforms(hermes_frontmatter),
                        "requires-tools": self._extract_tools(hermes_frontmatter),
                        "tags": hermes_meta.get("tags", []),
                        "category": self._map_category(hermes_meta.get("category", "other")),
                        "source": "hermes-agent",
                        "source_hash": compute_hash(content),
                    }
                }
            }
            
            # Check for tools that might not exist in JaegerAI
            hermes_tools = hermes_meta.get("requirements", {}).get("tools", [])
            missing_tools = self._check_missing_tools(hermes_tools)
            if missing_tools:
                warnings.append(f"Tools may not be available: {', '.join(missing_tools)}")
            
            # Format output
            jros_content = format_frontmatter(jros_frontmatter) + "\n\n" + body
            
            # Write output if directory provided
            output_path = None
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                skill_dir = output_dir / slug
                skill_dir.mkdir(parents=True, exist_ok=True)
                
                # Write SKILL.md
                output_path = skill_dir / "SKILL.md"
                output_path.write_text(jros_content, encoding="utf-8")
                
                # Copy additional files (references, scripts, etc.)
                if source_path.is_dir():
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
                warnings=warnings,
                metadata={
                    "original_version": hermes_frontmatter.get("version"),
                    "original_category": hermes_meta.get("category"),
                    "tools_mapped": hermes_tools,
                    "tags": hermes_meta.get("tags", []),
                },
            )
            
        except Exception as e:
            logger.exception(f"Failed to convert Hermes skill {source_path}")
            return ConversionResult(
                success=False,
                skill_name=source_path.name,
                source_format=self.source_format,
                errors=[str(e)],
            )

    def _detect_platforms(self, frontmatter: dict[str, Any]) -> list[str]:
        """Detect supported platforms from Hermes skill."""
        # Hermes doesn't specify platforms explicitly in most skills
        # Default to all platforms
        return ["linux", "macos", "windows"]

    def _check_missing_tools(self, tools: list[str]) -> list[str]:
        """Check which tools might not exist in JaegerAI."""
        # JaegerAI has ~96 tools, here are common Hermes tools that might differ
        jaeger_tool_names = {
            "terminal", "read_file", "write_file", "patch", "search_files",
            "web_search", "web_extract", "browser_exec", "vision_analyze",
            "image_generate", "text_to_speech", "memory", "session_search",
            "cronjob", "skills_list", "skill_view", "skill_manage",
            "todo", "clarify", "execute_code", "delegate_task",
            "read", "write", "edit", "grep", "glob", "bash", "shell",
            "computer", "execute_command", "run_command",
        }
        
        missing = []
        for tool in tools:
            # Normalize tool name
            normalized = tool.lower().replace("-", "_").replace(" ", "_")
            if normalized not in jaeger_tool_names:
                missing.append(tool)
        return missing


def import_hermes_skill(source_path: Path, output_dir: Path | None = None) -> ConversionResult:
    """Convenience function to import a Hermes skill."""
    adapter = HermesSkillAdapter()
    return adapter.convert(source_path, output_dir)


def import_hermes_skills_batch(
    source_dir: Path,
    output_dir: Path,
    *,
    pattern: str = "**/SKILL.md",
    limit: int | None = None,
) -> list[ConversionResult]:
    """Import multiple Hermes skills from a directory.

    Args:
        source_dir: Directory containing Hermes skills
        output_dir: Where to write converted skills
        pattern: Glob pattern to find SKILL.md files
        limit: Maximum number of skills to import

    Returns:
        List of conversion results
    """
    adapter = HermesSkillAdapter()
    results = []
    
    skill_files = list(source_dir.glob(pattern))
    if limit:
        skill_files = skill_files[:limit]
    
    for skill_file in skill_files:
        skill_dir = skill_file.parent
        result = adapter.convert(skill_dir, output_dir)
        results.append(result)
        status = "✓" if result.success else "✗"
        print(f"{status} {result.skill_name} ({result.source_format} → {result.target_format})")
        if result.warnings:
            for w in result.warnings:
                print(f"    ⚠️  {w}")
    
    successful = sum(1 for r in results if r.success)
    print(f"\nImported {successful}/{len(results)} skills successfully")
    
    return results
