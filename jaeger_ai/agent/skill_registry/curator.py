"""Skill Curator — keeps the agent-authored skill library from rotting.

Audit A2. Deep Think, reflection and `propose_deep_think_task` let the
agent write its own skills; nothing prunes them, so the library only
ever grows. The Curator is the background pass that maintains it.

Hard invariants — the Curator is conservative by construction:

  * **It never deletes.** "Archiving" is a non-destructive *move* into a
    timestamped archive directory; :func:`restore_skill` moves it back.
    The archive directory *is* the backup — fully reversible, no
    snapshot tarball needed.
  * **It only ever touches `origin == "agent"` skills.** A shipped
    (`builtin`), hand-written (`user`) or installed (`marketplace`)
    skill is `protected` and is never moved — this is exactly what the
    #8 provenance work was built to make safe.
  * **A pinned skill is protected** regardless of origin — drop a
    `.pinned` marker in its folder.
  * **It is conservative about "unused".** An agent skill that was used
    and then went idle past the staleness window is `stale` (a curation
    candidate). One that was *never* used is reported as `unused` but is
    **not** auto-archived — it might simply be new.

Consolidation (merging near-duplicate skills) is the riskiest part of
hermes's curator and is deliberately **not** ported — that needs LLM
judgement and careful merging, a separate effort.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jaeger_ai.agent.skill_registry.playbook_skills import PlaybookSkill, discover_playbooks

_PINNED_MARKER = ".pinned"
_ARCHIVED_FROM = ".archived_from"

# An agent skill idle for at least this long is a curation candidate.
_DEFAULT_STALE_DAYS = 30


# ── pinning ──────────────────────────────────────────────────────────


def is_pinned(folder: Path) -> bool:
    """True when a skill folder carries a ``.pinned`` marker."""
    return (Path(folder) / _PINNED_MARKER).exists()


def pin_skill(folder: Path) -> None:
    """Pin a skill — the Curator will never archive it."""
    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
        (Path(folder) / _PINNED_MARKER).write_text(
            "pinned — the curator will not archive this skill\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def unpin_skill(folder: Path) -> None:
    """Remove a skill's pin."""
    try:
        (Path(folder) / _PINNED_MARKER).unlink()
    except OSError:
        pass


# ── assessment ───────────────────────────────────────────────────────


@dataclass
class SkillAssessment:
    """One skill's curation verdict.

    ``status`` is one of: ``protected`` (origin != agent, or pinned),
    ``active`` (used recently), ``stale`` (a curation candidate),
    ``unused`` (agent-authored, never used — reported, not archived)."""

    name: str
    origin: str
    status: str
    folder: str
    last_used: str | None
    reason: str


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    # Treat a naive timestamp as UTC so the subtraction below is valid.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _classify(
    skill: PlaybookSkill,
    usage: dict[str, Any],
    stale_days: int,
    now: datetime,
) -> tuple[str, str]:
    """Return ``(status, reason)`` for one skill."""
    folder = skill.path.parent
    if skill.origin != "agent":
        return "protected", f"origin is '{skill.origin}' — not agent-authored"
    if is_pinned(folder):
        return "protected", "pinned"

    row = usage.get(skill.name) or {}
    last = _parse_iso(row.get("last_used"))
    if last is None:
        return "unused", "agent-authored but never used — review manually"
    age_days = (now - last).days
    if age_days >= stale_days:
        return "stale", f"agent-authored, last used {age_days}d ago"
    return "active", f"used {age_days}d ago"


def assess(
    skills: list[PlaybookSkill] | None = None,
    *,
    usage: dict[str, Any] | None = None,
    stale_days: int = _DEFAULT_STALE_DAYS,
    now: datetime | None = None,
) -> list[SkillAssessment]:
    """Assess every playbook skill. Pure — reads only, moves nothing."""
    if skills is None:
        skills = discover_playbooks()
    if usage is None:
        try:
            from jaeger_ai.core.runtime.usage_stats import snapshot
            usage = snapshot().get("skills", {})
        except Exception:  # noqa: BLE001
            usage = {}
    now = now or datetime.now(timezone.utc)

    out: list[SkillAssessment] = []
    for s in skills:
        status, reason = _classify(s, usage, stale_days, now)
        row = usage.get(s.name) or {}
        out.append(SkillAssessment(
            name=s.name, origin=s.origin, status=status,
            folder=str(s.path.parent),
            last_used=row.get("last_used") or None, reason=reason,
        ))
    return out


# ── archive / restore (non-destructive) ──────────────────────────────


def _archive_dir() -> Path:
    """Where archived skills live — always *outside* the scanned skills
    tree so an archived skill is not re-discovered."""
    try:
        from jaeger_ai.core.context import get_layout
        return get_layout().root / "skills_archived"
    except Exception:  # noqa: BLE001
        from jaeger_ai.agent.skill_registry.playbook_skills import _SKILLS_DIR
        return _SKILLS_DIR.parent / "skills_archived"


def archive_skill(folder: Path, *, archive_dir: Path | None = None) -> Path:
    """Move ``folder`` into the archive (non-destructive). Returns the
    new location. A ``.archived_from`` marker records the origin so
    :func:`restore_skill` can put it back exactly."""
    folder = Path(folder)
    archive_dir = Path(archive_dir) if archive_dir else _archive_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest_parent = archive_dir / stamp
    dest_parent.mkdir(parents=True, exist_ok=True)
    dest = dest_parent / folder.name
    shutil.move(str(folder), str(dest))
    try:
        (dest / _ARCHIVED_FROM).write_text(
            json.dumps({
                "original": str(folder),
                "archived_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"),
            }, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return dest


def list_archived(*, archive_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every archived skill — name, where it came from, when."""
    archive_dir = Path(archive_dir) if archive_dir else _archive_dir()
    if not archive_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for marker in archive_dir.rglob(_ARCHIVED_FROM):
        folder = marker.parent
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            info = {}
        out.append({
            "name": folder.name,
            "archived_path": str(folder),
            "original": info.get("original", ""),
            "archived_at": info.get("archived_at", ""),
        })
    return sorted(out, key=lambda r: r.get("archived_at", ""), reverse=True)


def restore_skill(
    name: str,
    *,
    archive_dir: Path | None = None,
) -> dict[str, Any]:
    """Move an archived skill back to where it came from. The rollback
    for :func:`archive_skill` — refuses to clobber a folder that already
    exists at the original path."""
    archive_dir = Path(archive_dir) if archive_dir else _archive_dir()
    for entry in list_archived(archive_dir=archive_dir):
        if entry["name"] != name:
            continue
        original = Path(entry["original"]) if entry["original"] else None
        if original is None:
            return {"ok": False, "error": "no recorded original path"}
        if original.exists():
            return {"ok": False, "error": f"{original} already exists — "
                                          "refusing to overwrite"}
        src = Path(entry["archived_path"])
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(original))
        try:
            (original / _ARCHIVED_FROM).unlink()
        except OSError:
            pass
        return {"ok": True, "name": name, "restored_to": str(original)}
    return {"ok": False, "error": f"no archived skill named {name!r}"}


# ── the curation pass ────────────────────────────────────────────────


def run_curation(
    *,
    apply: bool = False,
    skills: list[PlaybookSkill] | None = None,
    usage: dict[str, Any] | None = None,
    stale_days: int = _DEFAULT_STALE_DAYS,
    archive_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assess the skill library and, when ``apply`` is True, archive the
    stale agent-authored skills.

    ``apply`` defaults to **False** — the safe default is a dry run that
    only reports. Protected and unused skills are never archived; an
    archive failure on one skill never aborts the pass."""
    items = assess(skills, usage=usage, stale_days=stale_days, now=now)
    by_status: dict[str, list[SkillAssessment]] = {}
    for it in items:
        by_status.setdefault(it.status, []).append(it)

    archived: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    if apply:
        for it in by_status.get("stale", []):
            try:
                dest = archive_skill(Path(it.folder), archive_dir=archive_dir)
                archived.append({"name": it.name, "archived_to": str(dest)})
            except Exception as exc:  # noqa: BLE001 — one failure ≠ abort
                errors.append({"name": it.name,
                               "error": f"{type(exc).__name__}: {exc}"})

    return {
        "ok": True,
        "dry_run": not apply,
        "assessed": len(items),
        "counts": {k: len(v) for k, v in sorted(by_status.items())},
        "stale": [asdict(it) for it in by_status.get("stale", [])],
        "unused": [asdict(it) for it in by_status.get("unused", [])],
        "archived": archived,
        "errors": errors,
    }


__all__ = [
    "SkillAssessment",
    "archive_skill",
    "assess",
    "is_pinned",
    "list_archived",
    "pin_skill",
    "restore_skill",
    "run_curation",
    "unpin_skill",
]
