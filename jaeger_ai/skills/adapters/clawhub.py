"""ClawHub marketplace client and adapter.

ClawHub (clawhub.ai) is a marketplace for OpenClaw skills.
This module provides a client to search, download, and install skills.

API (partial, based on research):
- Search: GET https://clawhub.ai/api/v1/skills/search?q=<query>
- Get skill: GET https://clawhub.ai/api/v1/skills/<slug>
- Install: Download skill package (typically a zip or git repo)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import logging
import urllib.request
import urllib.error

from .base import SkillAdapter, ConversionResult
from .openclaw import OpenClawSkillAdapter

logger = logging.getLogger(__name__)

CLAWHUB_API_BASE = "https://clawhub.ai/api/v1"


@dataclass
class ClawHubSkill:
    """A skill from ClawHub."""
    slug: str
    name: str
    description: str
    version: str
    author: str
    license: str
    tags: list[str]
    downloads: int
    rating: float | None
    created_at: str
    updated_at: str
    registry_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "tags": self.tags,
            "downloads": self.downloads,
            "rating": self.rating,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "registry_url": self.registry_url,
        }


class ClawHubClient:
    """Client for the ClawHub marketplace API."""

    def __init__(self, api_base: str = CLAWHUB_API_BASE, api_key: str | None = None):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key

    def _request(self, endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """Make an API request."""
        from urllib.parse import urlencode
        
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
        
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "JaegerAI-Skills-Adapter/1.0")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error {e.code}: {e.reason}")
            raise
        except Exception as e:
            logger.error(f"Request failed: {e}")
            raise

    def search(self, query: str, *, limit: int = 20, tags: list[str] | None = None) -> list[ClawHubSkill]:
        """Search for skills on ClawHub."""
        params = {"q": query, "limit": str(limit)}
        if tags:
            params["tags"] = ",".join(tags)
        
        try:
            data = self._request("skills/search", params)
            skills = []
            for item in data.get("results", []):
                skills.append(ClawHubSkill(
                    slug=item.get("slug", ""),
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    version=item.get("version", "1.0.0"),
                    author=item.get("author", "unknown"),
                    license=item.get("license", "Unknown"),
                    tags=item.get("tags", []),
                    downloads=item.get("downloads", 0),
                    rating=item.get("rating"),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                    registry_url=item.get("registry_url", ""),
                ))
            return skills
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def get_skill(self, slug: str) -> ClawHubSkill | None:
        """Get details about a specific skill."""
        try:
            data = self._request(f"skills/{slug}")
            return ClawHubSkill(
                slug=data.get("slug", slug),
                name=data.get("name", ""),
                description=data.get("description", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", "unknown"),
                license=data.get("license", "Unknown"),
                tags=data.get("tags", []),
                downloads=data.get("downloads", 0),
                rating=data.get("rating"),
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
                registry_url=data.get("registry_url", ""),
            )
        except Exception as e:
            logger.error(f"Failed to get skill {slug}: {e}")
            return None

    def download_skill(self, slug: str, output_dir: Path) -> Path | None:
        """Download a skill package from ClawHub.

        Tries multiple methods:
        1. Git clone from registry URL
        2. Direct download of skill package
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        skill_dir = output_dir / slug
        
        # Method 1: Try git clone
        skill_info = self.get_skill(slug)
        if skill_info and skill_info.registry_url:
            import subprocess
            try:
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", skill_info.registry_url, str(skill_dir)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    logger.info(f"Cloned {slug} from {skill_info.registry_url}")
                    return skill_dir
            except Exception as e:
                logger.warning(f"Git clone failed for {slug}: {e}")
        
        # Method 2: Try direct API download
        try:
            data = self._request(f"skills/{slug}/download")
            download_url = data.get("download_url")
            if download_url:
                # Download and extract
                import zipfile
                import io
                
                with urllib.request.urlopen(download_url, timeout=60) as resp:
                    content = resp.read()
                
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    zf.extractall(skill_dir)
                
                return skill_dir
        except Exception as e:
            logger.warning(f"Direct download failed for {slug}: {e}")
        
        return None

    def install_skill(self, slug: str, output_dir: Path, convert: bool = True) -> ConversionResult:
        """Download and optionally convert a skill from ClawHub.

        Args:
            slug: Skill slug on ClawHub
            output_dir: Where to install the skill
            convert: Whether to convert to JROS format

        Returns:
            ConversionResult
        """
        # Download
        skill_dir = self.download_skill(slug, output_dir / "downloads")
        if not skill_dir:
            return ConversionResult(
                success=False,
                skill_name=slug,
                source_format="clawhub",
                errors=[f"Failed to download skill {slug}"],
            )
        
        if not convert:
            return ConversionResult(
                success=True,
                skill_name=slug,
                source_format="clawhub",
                output_path=skill_dir,
            )
        
        # Convert using OpenClaw adapter (ClawHub uses OpenClaw format)
        adapter = OpenClawSkillAdapter()
        result = adapter.convert(skill_dir, output_dir / "installed")
        result.source_format = "clawhub"
        return result


class ClawHubAdapter(SkillAdapter):
    """Adapter for ClawHub skills (uses OpenClaw adapter internally)."""

    source_format = "clawhub"

    def __init__(self, api_key: str | None = None):
        self.client = ClawHubClient(api_key=api_key)
        self._openclaw_adapter = OpenClawSkillAdapter()

    def _check_format(self, frontmatter: dict[str, Any]) -> bool:
        """Check if frontmatter is ClawHub format."""
        metadata = frontmatter.get("metadata", {})
        return "clawhub" in metadata

    def convert(self, source_path: Path, output_dir: Path | None = None) -> ConversionResult:
        """Convert a ClawHub skill (delegates to OpenClaw adapter)."""
        result = self._openclaw_adapter.convert(source_path, output_dir)
        result.source_format = self.source_format
        return result

    def search_and_install(
        self,
        query: str,
        output_dir: Path,
        *,
        limit: int = 5,
        auto_install: bool = False,
    ) -> list[dict[str, Any]]:
        """Search for skills and optionally install them.

        Args:
            query: Search query
            output_dir: Where to install skills
            limit: Maximum number of results
            auto_install: Whether to automatically install top results

        Returns:
            List of search results with install status
        """
        skills = self.client.search(query, limit=limit)
        results = []
        
        for skill in skills:
            result = {
                "skill": skill.to_dict(),
                "installed": False,
                "conversion": None,
            }
            
            if auto_install:
                conv = self.client.install_skill(skill.slug, output_dir)
                result["installed"] = conv.success
                result["conversion"] = conv.to_dict()
            
            results.append(result)
        
        return results


def install_from_clawhub(slug: str, output_dir: Path, api_key: str | None = None) -> ConversionResult:
    """Convenience function to install a skill from ClawHub."""
    client = ClawHubClient(api_key=api_key)
    return client.install_skill(slug, output_dir)
