"""Skill revision log — the audit trail of how a recipe-skill changed over time.

When the self-improvement loop (or the operator) keeps a new skill version, it
records a revision here — so you can see, per skill, HOW MANY times it's been
modified, WHEN, WHY, and the measured benchmark delta. The skill's version
(``_vN``) is the revision id; this log carries the story behind each bump (and,
with append-only versioning, the rollback path). Append-only JSONL at
``<instance>/memory/skill_revisions.jsonl``. See SKILL_EVOLUTION_PLAN.md.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SkillRevision:
    skill: str = ""
    version: str = ""                  # the _vN it created (e.g. "v3") — the revision id
    origin: str = "self-improvement"   # self-improvement | manual
    summary: str = ""                  # what changed
    delta: str = ""                    # measured benchmark delta, e.g. "+8%"
    ts: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_version(v: str) -> str:
    """Normalise '3' / 'v3' / '_v3' / 'weather_v3' -> 'v3' (the revision id)."""
    raw = str(v or "").strip().rsplit("_", 1)[-1].lstrip("v")
    return f"v{raw}" if raw else ""


def revisions_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "skill_revisions.jsonl"


def record(layout: Any, *, skill: str, version: str,
           origin: str = "self-improvement", summary: str = "",
           delta: str = "") -> SkillRevision:
    """Append a revision record — call it when a new skill version is KEPT."""
    r = SkillRevision(
        skill=(skill or "").strip(),
        version=_norm_version(version),
        origin=(origin or "self-improvement").strip(),
        summary=(summary or "").strip(),
        delta=str(delta or "").strip(),
        ts=_now(),
    )
    p = revisions_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return r


def _load(layout: Any) -> list[SkillRevision]:
    p = revisions_path(layout)
    if not p.exists():
        return []
    known = set(SkillRevision.__dataclass_fields__)
    out: list[SkillRevision] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:                       # a broken line never breaks the log
            d = json.loads(line)
            out.append(SkillRevision(**{k: v for k, v in d.items() if k in known}))
        except Exception:  # noqa: BLE001
            continue
    return out


def revisions_for(layout: Any, skill: str) -> list[SkillRevision]:
    s = (skill or "").strip()
    return [r for r in _load(layout) if r.skill == s]


def latest(layout: Any, skill: str) -> SkillRevision | None:
    revs = revisions_for(layout, skill)
    return revs[-1] if revs else None


def counts(layout: Any) -> dict[str, int]:
    """skill -> number of recorded revisions (how often it's been improved)."""
    agg: dict[str, int] = {}
    for r in _load(layout):
        agg[r.skill] = agg.get(r.skill, 0) + 1
    return agg
