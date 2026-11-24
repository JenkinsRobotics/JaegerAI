"""Versioned history for instance playbook skills (create / edit / rollback).

Every write to an instance ``skills/<name>/SKILL.md`` first snapshots the
current text to ``<instance>/memory/skill_history/<name>/vN.md`` and appends a
line to ``skill_revisions.jsonl`` (origin, summary). Rollback restores any
snapshot the same way, so a rollback is itself undoable. Builtin skills are
never written; the agent's writes stay inside the instance ``skills/`` dir.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jaeger_agent.skill_improvement import skill_revisions

MAX_BYTES = 64_000
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class SkillHistoryError(ValueError):
    pass


def _clean_name(name: str) -> str:
    from jaeger_skills import SkillValidationError, clean_skill_name
    try:
        return clean_skill_name(name)
    except SkillValidationError as exc:
        raise SkillHistoryError(str(exc)) from exc


def history_dir(layout: Any, name: str) -> Path:
    return Path(layout.root) / "memory" / "skill_history" / _clean_name(name)


def _frontmatter(text: str) -> dict[str, str]:
    from jaeger_skills import parse_frontmatter
    return parse_frontmatter(text)


def validate(name: str, content: str) -> str:
    from jaeger_skills import SkillValidationError, validate_skill_markdown
    try:
        return validate_skill_markdown(name, content)
    except SkillValidationError as exc:
        raise SkillHistoryError(str(exc)) from exc


def skill_folder(layout: Any, name: str) -> Path | None:
    """The instance folder that holds ``name`` (frontmatter name or folder name)."""
    root = Path(layout.skills_dir)
    if not root.is_dir():
        return None
    direct = root / name
    if (direct / "SKILL.md").is_file():
        return direct
    for f in root.rglob("SKILL.md"):
        rel = f.relative_to(root)
        if any(p.startswith(".") for p in rel.parts) or f.is_symlink():
            continue
        try:
            fm = _frontmatter(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        if (fm.get("name") or "").strip().lower() == name:
            return f.parent
    return None


def _builtin_taken(layout: Any, name: str) -> bool:
    from jaeger_agent.skill_registry import playbook_skills as pb
    variants = {name, name.replace("-", "_"), name.replace("_", "-")}
    if any(pb.find_playbook(v) is not None for v in variants):
        return True
    try:
        from jaeger_os.core.tools.tool_registry import get_tools
        if any(t.name in variants for t in get_tools()):
            return True
    except Exception:  # noqa: BLE001 — registry lookup is best-effort
        pass
    try:
        from jaeger_agent.skill_registry.skill_loader import discover_skills
        return any(sk.name in variants for sk in discover_skills(layout))
    except Exception:  # noqa: BLE001
        return False


def versions(layout: Any, name: str) -> list[dict[str, Any]]:
    d = history_dir(layout, name)
    rows = []
    revs = {r.version: r for r in skill_revisions.revisions_for(layout, _clean_name(name))}
    for p in sorted(d.glob("v*.md"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0):
        r = revs.get(p.stem)
        rows.append({"version": p.stem, "bytes": p.stat().st_size,
                     "ts": r.ts if r else "", "origin": r.origin if r else "",
                     "summary": r.summary if r else ""})
    return rows


def _next_version(layout: Any, name: str) -> str:
    d = history_dir(layout, name)
    nums = [int(p.stem[1:]) for p in d.glob("v*.md") if p.stem[1:].isdigit()]
    return f"v{(max(nums) if nums else 0) + 1}"


def write(layout: Any, name: str, content: str, *, summary: str,
          origin: str = "self-improvement", must_exist: bool | None = None) -> dict[str, Any]:
    """Create or replace an instance skill, snapshotting the new text as vN."""
    from jaeger_agent.skill_improvement.skill_maintenance import archive_lock
    from jaeger_agent.skill_registry import playbook_skills as pb

    name = _clean_name(name)
    text = validate(name, content)
    root = Path(layout.skills_dir)
    root.mkdir(parents=True, exist_ok=True)
    with archive_lock(root):
        folder = skill_folder(layout, name)
        if must_exist is True and folder is None:
            raise SkillHistoryError(f"No instance skill named {name!r}; builtin skills are read-only — create a new one instead")
        if must_exist is False and folder is not None:
            raise SkillHistoryError(f"Skill {name!r} already exists — use action='edit' or 'patch'")
        created = folder is None
        if created and _builtin_taken(layout, name):
            raise SkillHistoryError(f"{name!r} is already a builtin skill or tool name; pick a different name")
        folder = folder or root / name
        target = folder / "SKILL.md"
        hist = history_dir(layout, name)
        hist.mkdir(parents=True, exist_ok=True)
        if not created and target.is_file() and not any(hist.glob("v*.md")):
            # First managed edit of a pre-existing skill: keep its original as v0.
            (hist / "v0.md").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            return {"ok": True, "skill": name, "changed": False, "path": str(target)}
        version = _next_version(layout, name)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / ".SKILL.md.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)
        (hist / f"{version}.md").write_text(text, encoding="utf-8")
        if created:
            pb.mark_skill_origin(folder, "agent" if origin == "self-improvement" else "user")
    skill_revisions.record(layout, skill=name, version=version, origin=origin,
                           summary=(summary or ("created" if created else "edited"))[:300])
    return {"ok": True, "skill": name, "changed": True, "created": created,
            "version": version, "path": str(target)}


def rollback(layout: Any, name: str, version: str, *, origin: str = "manual") -> dict[str, Any]:
    name = _clean_name(name)
    v = "v" + str(version or "").strip().lstrip("v")
    snap = history_dir(layout, name) / f"{v}.md"
    if not snap.is_file():
        raise SkillHistoryError(f"{name!r} has no version {v}")
    if skill_folder(layout, name) is None:
        raise SkillHistoryError(f"{name!r} is not an instance skill")
    return write(layout, name, snap.read_text(encoding="utf-8"),
                 summary=f"rollback to {v}", origin=origin, must_exist=True)


def read_version(layout: Any, name: str, version: str) -> str:
    v = "v" + str(version or "").strip().lstrip("v")
    snap = history_dir(layout, _clean_name(name)) / f"{v}.md"
    if not snap.is_file():
        raise SkillHistoryError(f"{name!r} has no version {v}")
    return snap.read_text(encoding="utf-8")
