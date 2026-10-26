"""OpenClaw skill adapter.

Converts OpenClaw/ClawHub SKILL.md format to JaegerAI JROS skill format.

OpenClaw format:
```yaml
---
name: skill-name
description: "..."
license: MIT
metadata:
  openclaw:
    emoji: "🔧"
    requires:
      bins: [command1]
      env: [VAR1]
    install:
      - id: brew
        kind: brew
        formula: package
        bins: [command]
  clawhub:
    emoji: "📦"
    license: MIT
    requires:
      env: [API_KEY]
---

# Skill Title

## Description
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


class OpenClawSkillAdapter(SkillAdapter):
    """Adapter for OpenClaw/ClawHub skills."""

    source_format = "openclaw"

    def _check_format(self, frontmatter: dict[str, Any]) -> bool:
        """Check if frontmatter is OpenClaw format."""
        metadata = frontmatter.get("metadata", {})
        return "openclaw" in metadata or "clawhub" in metadata

    def convert(self, source_path: Path, output_dir: Path | None = None) -> ConversionResult:
        """Convert an OpenClaw skill to JROS format."""
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
            openclaw_frontmatter, body = parse_frontmatter(content)
            
            # Extract OpenClaw metadata
            metadata = openclaw_frontmatter.get("metadata", {})
            openclaw_meta = metadata.get("openclaw", {})
            clawhub_meta = metadata.get("clawhub", {})
            
            skill_name = openclaw_frontmatter.get("name", skill_md_path.parent.name)
            slug = slugify(skill_name)
            
            warnings = []
            
            # Extract install requirements
            install_steps = openclaw_meta.get("install", [])
            requires_bins = openclaw_meta.get("requires", {}).get("bins", [])
            requires_env = openclaw_meta.get("requires", {}).get("env", [])
            
            # ClawHub specific
            clawhub_requires_env = clawhub_meta.get("requires", {}).get("env", [])
            requires_env.extend(clawhub_requires_env)
            
            if install_steps:
                warnings.append(f"Install steps required: {len(install_steps)} package(s)")
            if requires_env:
                warnings.append(f"Environment variables required: {', '.join(requires_env)}")
            
            # Build JROS frontmatter
            jros_frontmatter: dict[str, Any] = {
                "name": skill_name,
                "description": openclaw_frontmatter.get("description", ""),
                "license": openclaw_frontmatter.get("license", clawhub_meta.get("license", "Unknown")),
                "metadata": {
                    "jros": {
                        "version": "1.0.0",
                        "lifecycle": "imported",
                        "skill-class": "first-class",
                        "platforms": self._detect_platforms(openclaw_frontmatter),
                        "requires-tools": self._extract_tools(openclaw_frontmatter),
                        "requires-bins": requires_bins,
                        "requires-env": requires_env,
                        "tags": [],
                        "category": "imported",
                        "emoji": openclaw_meta.get("emoji") or clawhub_meta.get("emoji", ""),
                        "source": "openclaw",
                        "source_hash": compute_hash(content),
                    }
                }
            }
            
            # Add install instructions to body
            if install_steps:
                install_section = self._format_install_section(install_steps)
                body = install_section + "\n\n" + body
            
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
                
                # Copy additional files
                if source_path.is_dir():
                    for item in source_path.iterdir():
                        if item.name != "SKILL.md" and item.is_dir():
                            dest = skill_dir / item.name
                            if not dest.exists():
                                shutil.copytree(item, dest)
                        elif item.is_file() and item.suffix in (".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml"):
                            shutil.copy2(item, skill_dir)
            
            return ConversionResult(
                success=True,
                skill_name=skill_name,
                source_format=self.source_format,
                output_path=output_path,
                warnings=warnings,
                metadata={
                    "emoji": openclaw_meta.get("emoji") or clawhub_meta.get("emoji"),
                    "requires_bins": requires_bins,
                    "requires_env": requires_env,
                    "install_steps": len(install_steps),
                },
            )
            
        except Exception as e:
            logger.exception(f"Failed to convert OpenClaw skill {source_path}")
            return ConversionResult(
                success=False,
                skill_name=source_path.name,
                source_format=self.source_format,
                errors=[str(e)],
            )

    def _detect_platforms(self, frontmatter: dict[str, Any]) -> list[str]:
        """Detect supported platforms from OpenClaw skill."""
        # Check for OS-specific requirements
        metadata = frontmatter.get("metadata", {})
        openclaw_meta = metadata.get("openclaw", {})
        
        platforms = []
        
        # Check install steps for platform hints
        for step in openclaw_meta.get("install", []):
            kind = step.get("kind", "")
            if kind == "brew":
                platforms.append("macos")
            elif kind == "apt":
                platforms.append("linux")
            elif kind == "npm":
                platforms.extend(["linux", "macos", "windows"])
        
        if not platforms:
            platforms = ["linux", "macos", "windows"]
        
        return list(dict.fromkeys(platforms))  # Dedupe

    def _format_install_section(self, install_steps: list[dict[str, Any]]) -> str:
        """Format install steps as markdown section."""
        lines = ["## Installation Requirements", ""]
        lines.append("This skill requires the following dependencies:")
        lines.append("")
        
        for step in install_steps:
            kind = step.get("kind", "unknown")
            label = step.get("label", kind)
            bins = step.get("bins", [])
            
            lines.append(f"- **{label}**")
            if bins:
                lines.append(f"  - Provides: {', '.join(bins)}")
        
        lines.append("")
        return "\n".join(lines)


def import_openclaw_skill(source_path: Path, output_dir: Path | None = None) -> ConversionResult:
    """Convenience function to import an OpenClaw skill."""
    adapter = OpenClawSkillAdapter()
    return adapter.convert(source_path, output_dir)


def import_openclaw_skills_batch(
    source_dir: Path,
    output_dir: Path,
    *,
    pattern: str = "**/SKILL.md",
    limit: int | None = None,
) -> list[ConversionResult]:
    """Import multiple OpenClaw skills from a directory."""
    adapter = OpenClawSkillAdapter()
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
