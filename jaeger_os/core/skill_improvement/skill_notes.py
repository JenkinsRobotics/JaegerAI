"""Skill usage notes — the per-use journal that feeds skill self-improvement.

The agent jots a SHORT note after a notable skill use (smooth / slow / hit
issues / failed) via the ``skill_note`` tool. Notes ACCUMULATE per skill; when a
skill's notes pile up (or it keeps misbehaving) the agent proposes a Deep Think
task to review them and improve the recipe — measured against the prior version
(smoke test + ``benchmark_skill``), keep-if-better. See
``dev/docs/process/SKILL_EVOLUTION_PLAN.md``.

This module is **phase 1**: capture the signal. It does NOT trigger reviews or
rewrite anything (phases 2-4). One append-only JSONL at
``<instance>/memory/skill_notes.jsonl`` — cheap to write in a live turn, easy to
query by skill for the reviewer.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# smooth/slow/issues/failed are agent-written (how a use went). "reviewing" is
# a lifecycle marker the review loop writes when it queues a Deep Think pass —
# it resets the "needs review?" counter so a finished review isn't re-proposed.
OUTCOMES = ("smooth", "slow", "issues", "failed", "reviewing")


@dataclass
class SkillNote:
    skill: str = ""
    outcome: str = "smooth"      # smooth | slow | issues | failed
    note: str = ""               # the agent's terse, concrete observation
    ts: str = ""
    objective: str = ""          # the task objective, verbatim (1 line)
    calls: int = 0               # tool-call count for this use
    procedure: str = ""          # brief ordered procedure (the calls)
    errors: str = ""             # errors / retries / dead-ends
    flag: bool = False           # agent asks for review (fast-path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def notes_path(layout: Any) -> Path:
    return Path(layout.root) / "memory" / "skill_notes.jsonl"


def add_note(layout: Any, *, skill: str, outcome: str, note: str = "",
             objective: str = "", calls: int = 0, procedure: str = "",
             errors: str = "", flag: bool = False) -> SkillNote:
    """Append a structured post-use summary — one JSONL line, no model call.
    An unknown ``outcome`` is recorded as ``issues`` (still worth a signal)."""
    out = (outcome or "smooth").strip().lower()
    n = SkillNote(skill=(skill or "").strip(),
                  outcome=out if out in OUTCOMES else "issues",
                  note=(note or "").strip(), ts=_now(),
                  objective=(objective or "").strip(), calls=int(calls or 0),
                  procedure=(procedure or "").strip(),
                  errors=(errors or "").strip(), flag=bool(flag))
    p = notes_path(layout)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(n), ensure_ascii=False) + "\n")
    return n


def _load(layout: Any) -> list[SkillNote]:
    p = notes_path(layout)
    if not p.exists():
        return []
    known = set(SkillNote.__dataclass_fields__)
    out: list[SkillNote] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:                       # a broken line never breaks the journal
            d = json.loads(line)
            out.append(SkillNote(**{k: v for k, v in d.items() if k in known}))
        except Exception:  # noqa: BLE001
            continue
    return out


def notes_for(layout: Any, skill: str) -> list[SkillNote]:
    s = (skill or "").strip()
    return [n for n in _load(layout) if n.skill == s]


def all_notes(layout: Any) -> list[SkillNote]:
    return _load(layout)


def summary(layout: Any) -> dict[str, dict[str, int]]:
    """Per-skill outcome tally — the at-a-glance "which skills are struggling"
    signal the reviewer + the operator read (e.g. {"time": {"failed": 3, …}})."""
    agg: dict[str, dict[str, int]] = {}
    for n in _load(layout):
        tally = agg.setdefault(n.skill, {o: 0 for o in OUTCOMES})
        tally[n.outcome] = tally.get(n.outcome, 0) + 1
    return agg
