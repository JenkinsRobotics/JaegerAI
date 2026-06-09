"""Skill packaging — bundle an instance skill into a portable artifact.

The foundation of the skill marketplace (see docs/marketplace_spec.md).
``package_skill`` takes a skill the agent built in ``<instance>/skills/``
and produces:

  • a ``.zip`` bundle of the skill folder
  • a ``skill_manifest.json`` inside it — the metadata the marketplace
    catalog references (name, version, author, deps, smoke-test status,
    integrity hash, …)

Packaging is useful standalone — it doesn't need the marketplace to
exist. ``submit_skill`` (a later phase) just reuses the bundle this
produces and pushes it to the marketplace GitHub repo.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
except Exception:  # noqa: BLE001
    _yaml = None  # type: ignore[assignment]


def _read_skill_frontmatter(skill_dir: Path) -> dict[str, Any]:
    """Parse the YAML frontmatter block from a skill's SKILL.md.

    SKILL.md shape: ``---\\n<yaml>\\n---\\n<body>``. Returns the parsed
    mapping, or an empty dict when there's no frontmatter / no SKILL.md.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file() or _yaml is None:
        return {}
    text = skill_md.read_text(encoding="utf-8")
    if not text.lstrip().startswith("---"):
        return {}
    # Split on the frontmatter fences: ['', '<yaml>', '<body>'].
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = _yaml.safe_load(parts[1])
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _run_smoke_test(skill_dir: Path) -> str:
    """Run the skill's smoke test if present. Returns 'pass', 'fail',
    or 'absent'."""
    smoke = skill_dir / "tests" / "smoke_test.py"
    if not smoke.is_file():
        return "absent"
    try:
        proc = subprocess.run(
            [sys.executable, str(smoke)],
            capture_output=True, text=True, timeout=60,
            cwd=str(skill_dir),
        )
        return "pass" if proc.returncode == 0 else "fail"
    except Exception:  # noqa: BLE001
        return "fail"


def _extract_dependencies(frontmatter: dict[str, Any]) -> list[str]:
    """Pull the pip dependency list out of SKILL.md frontmatter.

    Tolerates a couple of shapes: a top-level ``dependencies:`` list, or
    a ``requires:`` block with a ``libraries:`` list (the plugin-manifest
    convention)."""
    deps = frontmatter.get("dependencies")
    if isinstance(deps, list):
        return [str(d) for d in deps]
    requires = frontmatter.get("requires")
    if isinstance(requires, dict):
        libs = requires.get("libraries")
        if isinstance(libs, list):
            return [str(d) for d in libs]
    return []


def find_skill_dir(layout: Any, skill_name: str) -> Path | None:
    """Resolve a skill name to its folder under ``<instance>/skills/``.

    Accepts an exact folder name (``weather_report_v2``) or a bare name
    (``weather_report``) — in the bare case the highest ``_vN`` wins."""
    skills_root = layout.skills_dir
    if not skills_root.is_dir():
        return None
    exact = skills_root / skill_name
    if exact.is_dir():
        return exact
    # Bare name → find <name>_v<N>, highest N.
    matches: list[tuple[int, Path]] = []
    for child in skills_root.iterdir():
        if not child.is_dir():
            continue
        nm = child.name
        if nm == skill_name:
            return child
        if nm.startswith(skill_name + "_v") and nm[len(skill_name) + 2:].isdigit():
            matches.append((int(nm[len(skill_name) + 2:]), child))
    if matches:
        return max(matches, key=lambda m: m[0])[1]
    return None


def package_skill(layout: Any, skill_name: str) -> dict[str, Any]:
    """Bundle ``skill_name`` from ``<instance>/skills/`` into a portable
    ``.zip`` with a generated ``skill_manifest.json``.

    Returns ``{ok, skill, version, package_path, manifest}`` on success
    or ``{ok: False, error: ...}``. Never raises — the agent gets a
    structured result.
    """
    skill_dir = find_skill_dir(layout, skill_name)
    if skill_dir is None:
        return {
            "ok": False,
            "skill": skill_name,
            "error": (f"no skill folder {skill_name!r} under "
                      f"{layout.skills_dir} — check /deepthink or list_skill_dir"),
        }

    frontmatter = _read_skill_frontmatter(skill_dir)
    folder = skill_dir.name
    # Derive name + version from "<name>_v<N>" when possible, else the
    # folder name as-is + version 1.
    name = frontmatter.get("name") or folder
    version = frontmatter.get("version")
    if version is None and "_v" in folder and folder.rsplit("_v", 1)[1].isdigit():
        name = folder.rsplit("_v", 1)[0]
        version = int(folder.rsplit("_v", 1)[1])
    if version is None:
        version = 1

    smoke = _run_smoke_test(skill_dir)

    # Author from the instance identity, best-effort.
    author = "unknown"
    try:
        from jaeger_os.core.instance.schemas import Identity, load_yaml
        identity = load_yaml(layout.identity_path, Identity)
        author = identity.name
    except Exception:  # noqa: BLE001
        pass

    # Core version for the install-time compat check.
    schema_version = ""
    try:
        from jaeger_os.core.instance.schemas import SCHEMA_VERSION
        schema_version = str(SCHEMA_VERSION)
    except Exception:  # noqa: BLE001
        pass

    # Collect the skill's files (relative paths, sorted, skip pycache).
    files: list[Path] = sorted(
        p for p in skill_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    rel_files = [str(p.relative_to(skill_dir)) for p in files]

    manifest: dict[str, Any] = {
        "name": name,
        "version": version,
        "description": (frontmatter.get("description") or "").strip(),
        "author": author,
        "category": frontmatter.get("category", "cognitive"),
        "kind": frontmatter.get("kind", "agent_authored"),
        "permission_tier": frontmatter.get("permission_tier", 0),
        "dependencies": _extract_dependencies(frontmatter),
        "jaeger_schema_version": schema_version,
        "smoke_test": smoke,
        "entry_files": rel_files,
        "packaged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Write the bundle: <instance>/packaged_skills/<name>-v<version>.zip
    out_dir = layout.root / "packaged_skills"
    out_dir.mkdir(parents=True, exist_ok=True)
    pkg_path = out_dir / f"{name}-v{version}.zip"

    with zipfile.ZipFile(pkg_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in files:
            zf.write(src, arcname=str(Path(name) / src.relative_to(skill_dir)))
        # The manifest goes in last so its hash field can cover the
        # skill files; we compute the hash over the file payload only.
        payload = b"".join(p.read_bytes() for p in files)
        manifest["package_sha256"] = hashlib.sha256(payload).hexdigest()
        zf.writestr(
            str(Path(name) / "skill_manifest.json"),
            json.dumps(manifest, indent=2, ensure_ascii=False),
        )

    return {
        "ok": True,
        "skill": name,
        "version": version,
        "package_path": str(pkg_path),
        "smoke_test": smoke,
        "manifest": manifest,
    }
