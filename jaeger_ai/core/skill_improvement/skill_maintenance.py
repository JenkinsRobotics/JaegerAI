"""Skill lifecycle — archive superseded versions, score skills from their
post-use notes, and retire (recoverably) agent-owned skills that never win.

Instance zone only (`<instance>/skills/`); everything **moves to ``.archive/``,
never deletes**. The loader scans direct children + matches ``<name>_v<N>``, so
``.archive/`` is invisible to skill discovery. The retirement guard never
touches a user-written skill. See dev/docs/history/SKILL_EVOLUTION_PLAN.md §6-§7.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from jaeger_ai.core.skill_improvement import skill_notes, skill_revisions

_VN = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)_v(?P<v>\d+)$")
ARCHIVE_DIR = ".archive"
_WIN = "smooth"


def skills_root(layout: Any) -> Path:
    return Path(layout.root) / "skills"


def skill_score(layout: Any, skill: str) -> dict:
    """uses / wins / win_rate from the post-use notes ('reviewing' markers don't
    count as uses; 'smooth' is a win)."""
    notes = [n for n in skill_notes.notes_for(layout, skill)
             if n.outcome != "reviewing"]
    uses = len(notes)
    wins = sum(1 for n in notes if n.outcome == _WIN)
    return {"uses": uses, "wins": wins,
            "win_rate": (wins / uses) if uses else 0.0}


def _eligible_for_retire(layout: Any, skill: str) -> bool:
    """Agent-owned only: at least one ``self-improvement`` revision AND no
    ``manual`` one. Untouched skills (no revisions) are never auto-retired."""
    revs = skill_revisions.revisions_for(layout, skill)
    if not revs:
        return False
    if any(r.origin == "manual" for r in revs):
        return False
    return any(r.origin == "self-improvement" for r in revs)


def _versions_of(root: Path, skill: str) -> list[tuple[int, Path]]:
    out = []
    for child in root.iterdir():
        m = _VN.match(child.name)
        if child.is_dir() and m and m.group("name") == skill:
            out.append((int(m.group("v")), child))
    out.sort()                            # ascending; newest last
    return out


def _move_to_archive(root: Path, d: Path) -> str:
    archive = root / ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)
    dest = archive / d.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(d), str(dest))
    return d.name


def archive_superseded_versions(layout: Any, skill: str, *, keep: int = 2) -> list[str]:
    """Move all but the newest ``keep`` ``<skill>_vN`` dirs into ``.archive/``.
    Recoverable; the loader never sees ``.archive/``."""
    root = skills_root(layout)
    if not root.is_dir():
        return []
    versions = _versions_of(root, skill)
    superseded = versions[:-keep] if keep > 0 else versions
    return [_move_to_archive(root, d) for _v, d in superseded]


def retire_candidates(layout: Any, *, min_uses: int = 5,
                      max_win_rate: float = 0.34) -> list[str]:
    """Agent-owned skills with enough uses and a poor win-rate."""
    out = []
    for skill in skill_notes.summary(layout):
        if not _eligible_for_retire(layout, skill):
            continue
        s = skill_score(layout, skill)
        if s["uses"] >= min_uses and s["win_rate"] <= max_win_rate:
            out.append(skill)
    return out


def retire(layout: Any, skill: str) -> dict:
    """Move every active version of ``skill`` to ``.archive/`` (recoverable) and
    record the retirement. Refuses a non-eligible (user-owned/untouched) skill."""
    if not _eligible_for_retire(layout, skill):
        return {"retired": False, "reason": "not eligible (user-owned/untouched)"}
    root = skills_root(layout)
    moved = [_move_to_archive(root, d) for _v, d in _versions_of(root, skill)]
    skill_revisions.record(layout, skill=skill, version="retired",
                           origin="self-improvement",
                           summary="retired: low win-rate", delta="")
    return {"retired": bool(moved), "moved": moved}


def maintenance_sweep(layout: Any, *, keep: int = 2) -> dict:
    """Idle maintenance: archive each skill's superseded versions, then retire
    eligible low-win skills. Recoverable + guarded throughout."""
    archived: dict[str, list[str]] = {}
    for skill in list(skill_notes.summary(layout)):
        moved = archive_superseded_versions(layout, skill, keep=keep)
        if moved:
            archived[skill] = moved
    retired = []
    for skill in retire_candidates(layout):
        if retire(layout, skill).get("retired"):
            retired.append(skill)
    return {"archived": archived, "retired": retired}


__all__ = [
    "skills_root", "skill_score", "archive_superseded_versions",
    "retire_candidates", "retire", "maintenance_sweep", "ARCHIVE_DIR",
]
