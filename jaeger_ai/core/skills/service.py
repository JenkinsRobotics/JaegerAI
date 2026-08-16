"""Validated skill catalog and mutations for external Jaeger surfaces."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from jaeger_ai.core.instance.schemas import Config, dump_yaml, load_yaml


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_SKILL_BYTES = 2_000_000


class SkillServiceError(ValueError):
    pass


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not _NAME.fullmatch(name) or name in {".", ".."}:
        raise SkillServiceError("invalid skill name")
    return name


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _playbook_module():
    from jaeger_agent.skill_registry import playbook_skills

    return playbook_skills


def _playbook_rows(layout: Any) -> list[dict[str, Any]]:
    pb = _playbook_module()
    roots = ((Path(pb._SKILLS_DIR), "builtin"), (Path(layout.skills_dir), "instance"))
    disabled = set(load_yaml(layout.config_path, Config).skills.disabled_playbooks)
    by_name: dict[str, dict[str, Any]] = {}
    for root, zone in roots:
        if not root.is_dir():
            continue
        for skill_file in sorted(root.rglob("SKILL.md")):
            if skill_file.is_symlink() or not _within(root, skill_file):
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            fm = pb._parse_frontmatter(text)
            if fm.get("archived"):
                continue
            name = str(fm.get("name") or skill_file.parent.name).strip()
            if not name:
                continue
            try:
                rel = skill_file.parent.relative_to(root)
                category = rel.parts[0] if len(rel.parts) > 1 else "general"
            except ValueError:
                category = "general"
            by_name[name] = {
                "name": name,
                "description": str(fm.get("description") or "").strip(),
                "category": category,
                "origin": pb.read_skill_origin(skill_file.parent) if zone == "instance" else "builtin",
                "zone": zone,
                "kinds": ["playbook"],
                "disabled": name in disabled,
                "mutable": zone == "instance",
            }
    return list(by_name.values())


def _code_rows(layout: Any) -> list[dict[str, Any]]:
    from jaeger_agent.skill_registry.skill_loader import discover_skills

    allowlist = set(load_yaml(layout.config_path, Config).skills.enabled_base_skills)
    rows = []
    for skill in discover_skills(layout):
        disabled = skill.zone == "core" and bool(allowlist) and skill.name not in allowlist
        rows.append({
            "name": skill.name,
            "description": str(getattr(skill.manifest, "description", "") or ""),
            "category": str(getattr(skill.manifest, "category", "") or "tools"),
            "origin": "builtin" if skill.zone == "core" else "instance",
            "zone": "builtin" if skill.zone == "core" else "instance",
            "version": skill.version_str,
            "kinds": ["tool"],
            "disabled": disabled,
            "mutable": skill.zone == "instance",
        })
    return rows


def list_skills(layout: Any) -> dict[str, Any]:
    """Return the effective skill catalog with provenance and mutability."""
    merged: dict[str, dict[str, Any]] = {}
    for row in [*_playbook_rows(layout), *_code_rows(layout)]:
        existing = merged.get(row["name"])
        if existing is None:
            merged[row["name"]] = row
            continue
        existing["kinds"] = sorted(set(existing["kinds"] + row["kinds"]))
        existing["disabled"] = bool(existing["disabled"] and row["disabled"])
        existing["mutable"] = bool(existing["mutable"] or row["mutable"])
        if not existing.get("description"):
            existing["description"] = row.get("description", "")
    return {
        "skills": sorted(merged.values(), key=lambda row: (row.get("category", ""), row["name"].lower())),
        "skill_runtime_available": True,
        "owner": "jaeger",
    }


def _find_playbook(layout: Any, name: str) -> tuple[Path, Path, str]:
    wanted = _name(name)
    pb = _playbook_module()
    for root, zone in ((Path(layout.skills_dir), "instance"), (Path(pb._SKILLS_DIR), "builtin")):
        if not root.is_dir():
            continue
        for skill_file in root.rglob("SKILL.md"):
            if skill_file.is_symlink() or not _within(root, skill_file):
                continue
            try:
                fm = pb._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if str(fm.get("name") or skill_file.parent.name) == wanted:
                return skill_file.parent, skill_file, zone
    raise SkillServiceError(f"skill {wanted!r} not found")


def get_skill(layout: Any, name: str, linked_file: str | None = None) -> dict[str, Any]:
    folder, skill_file, zone = _find_playbook(layout, name)
    target = skill_file
    display_path = "SKILL.md"
    if linked_file:
        target = folder / str(linked_file)
        if target.is_symlink() or not _within(folder, target) or not target.is_file():
            raise SkillServiceError("invalid linked skill file")
        display_path = str(target.relative_to(folder))
    if target.stat().st_size > _MAX_SKILL_BYTES:
        raise SkillServiceError("skill file exceeds the 2 MB limit")
    content = target.read_text(encoding="utf-8")
    pb = _playbook_module()
    fm = pb._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    linked: dict[str, list[str]] = {}
    for child in folder.rglob("*"):
        if child.is_file() and not child.is_symlink() and child != skill_file:
            rel = child.relative_to(folder)
            linked.setdefault(rel.parts[0], []).append(str(rel))
    return {
        "success": True,
        "name": str(fm.get("name") or folder.name),
        "description": str(fm.get("description") or ""),
        "content": content,
        "path": display_path,
        "linked_files": {key: sorted(values) for key, values in linked.items()},
        "origin": zone,
        "mutable": zone == "instance",
        "owner": "jaeger",
    }


def install_skill(layout: Any, name: str, content: str, category: str = "") -> dict[str, Any]:
    """Install or update one instance-owned playbook atomically."""
    normalized = _name(name)
    category = str(category or "").strip()
    if category and not _NAME.fullmatch(category):
        raise SkillServiceError("invalid skill category")
    encoded = str(content or "").encode("utf-8")
    if not encoded or len(encoded) > _MAX_SKILL_BYTES:
        raise SkillServiceError("skill content must be between 1 byte and 2 MB")
    pb = _playbook_module()
    fm = pb._parse_frontmatter(encoded.decode("utf-8"))
    declared = str(fm.get("name") or normalized).strip()
    if declared != normalized:
        raise SkillServiceError("skill name must match the SKILL.md frontmatter name")
    root = Path(layout.skills_dir)
    destination = root / category / normalized if category else root / normalized
    if not _within(root, destination) or destination.is_symlink():
        raise SkillServiceError("invalid skill destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_dir():
            raise SkillServiceError("skill destination is not a directory")
        skill_file = destination / "SKILL.md"
        if skill_file.is_symlink():
            raise SkillServiceError("refusing to replace a symlinked skill file")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".SKILL-", suffix=".md", dir=destination)
        temporary_file = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_file, skill_file)
        finally:
            temporary_file.unlink(missing_ok=True)
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{normalized}-", dir=destination.parent))
        try:
            (temporary / "SKILL.md").write_bytes(encoded)
            pb.mark_skill_origin(temporary, "user")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {"ok": True, "name": normalized, "owner": "jaeger", "restart_required": False}


def clone_skill(layout: Any, name: str) -> dict[str, Any]:
    """Clone a bundled playbook into the instance without overwriting."""
    normalized = _name(name)
    folder, _skill_file, zone = _find_playbook(layout, normalized)
    if zone != "builtin":
        raise SkillServiceError("only bundled skills can be cloned")
    destination = Path(layout.skills_dir) / normalized
    if destination.exists():
        raise SkillServiceError("an instance skill with this name already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, destination, symlinks=False)
    _playbook_module().mark_skill_origin(destination, "user")
    return {"ok": True, "name": normalized, "owner": "jaeger", "restart_required": False}


def set_skill_enabled(layout: Any, name: str, enabled: bool) -> dict[str, Any]:
    normalized = _name(name)
    catalog = {row["name"]: row for row in list_skills(layout)["skills"]}
    if normalized not in catalog:
        raise SkillServiceError(f"skill {normalized!r} not found")
    cfg = load_yaml(layout.config_path, Config)
    disabled = list(dict.fromkeys(str(item) for item in cfg.skills.disabled_playbooks))
    if enabled:
        cfg.skills.disabled_playbooks = [item for item in disabled if item != normalized]
    elif normalized not in disabled:
        cfg.skills.disabled_playbooks = [*disabled, normalized]

    core_names = {row["name"] for row in _code_rows(layout) if row["zone"] == "builtin"}
    if normalized in core_names:
        allowlist = set(cfg.skills.enabled_base_skills) or set(core_names)
        if enabled:
            allowlist.add(normalized)
        else:
            allowlist.discard(normalized)
        cfg.skills.enabled_base_skills = sorted(allowlist)
    dump_yaml(layout.config_path, Config.model_validate(cfg.model_dump()))
    return {
        "ok": True, "name": normalized, "enabled": bool(enabled),
        "owner": "jaeger", "restart_required": normalized in core_names,
    }


def remove_skill(layout: Any, name: str) -> dict[str, Any]:
    normalized = _name(name)
    folder, _skill_file, zone = _find_playbook(layout, normalized)
    if zone != "instance" or not _within(Path(layout.skills_dir), folder):
        raise SkillServiceError("bundled skills cannot be removed; disable or clone them instead")
    if folder.is_symlink():
        raise SkillServiceError("refusing to remove a symlinked skill")
    shutil.rmtree(folder)
    return {"ok": True, "name": normalized, "owner": "jaeger", "restart_required": False}
