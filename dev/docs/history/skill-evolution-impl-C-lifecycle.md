# Skill Evolution — Plan C: Archive + Scoring/Retirement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Give skills a lifecycle — superseded playbook versions move to a per-skill archive (the only history for gitignored instance skills), and an idle maintenance sweep scores skills from their notes and retires (recoverably) agent-owned skills that never win, never touching user-written ones.

**Architecture:** A new `jaeger_os/core/skill_maintenance.py` — pure-ish functions over the instance skills dir (`<instance>/skills/`) + `skill_notes` + `skill_revisions`. `archive_superseded_versions` keeps the top-K `<name>_vN` active and moves the rest to `<instance>/skills/.archive/` (the loader scans direct children + matches `<name>_v<N>`, so `.archive/` is invisible to discovery). `skill_score` derives uses/wins/win-rate from notes (no new tracking). `retire` moves a skill to `.archive` (recoverable), guarded so only agent-owned (`origin=self-improvement`, no `manual` revision) low-win skills are eligible. `maintenance_sweep` runs both, wired into the Deep-Think idle loop next to the review sweep. A `jaeger skills score` readout surfaces it.

**Tech Stack:** Python stdlib (`shutil`, `pathlib`) + pytest.

## Global Constraints

- **Recoverable, never destructive** — retirement and archiving MOVE to `.archive/`, never delete.
- **Never auto-retire a user-written skill** — eligible only if it has a `self-improvement` revision AND no `manual` revision.
- Don't touch the **core** zone (`jaeger_os/agent/skills/`) — instance zone only.
- No new dependencies. Tests via `.venv/bin/python -m pytest`. No `Co-Authored-By` trailer.

## File Structure

- `jaeger_os/core/skill_maintenance.py` — CREATE: `skills_root`, `skill_score`, `archive_superseded_versions`, `_eligible_for_retire`, `retire_candidates`, `retire`, `maintenance_sweep`.
- `jaeger_os/main.py` — MODIFY: idle loop calls `maintenance_sweep`; add a `jaeger skills score` path (or `skills_cmd`).
- `jaeger_os/cli/skills_cmd.py` — MODIFY: `score` subcommand.
- `dev/tests/jaeger_os/core/test_skill_maintenance.py` — CREATE.

---

### Task 1: `skill_score` + retirement eligibility

**Files:** Create `jaeger_os/core/skill_maintenance.py`; Test `dev/tests/jaeger_os/core/test_skill_maintenance.py`

**Interfaces:**
- Consumes: `skill_notes.summary`/`notes_for`; `skill_revisions.revisions_for`.
- Produces: `skills_root(layout) -> Path`; `skill_score(layout, skill) -> dict` (`{uses, wins, win_rate}`); `_eligible_for_retire(layout, skill) -> bool`.

- [ ] **Step 1: failing test**

```python
import pathlib, tempfile
from jaeger_os.core import skill_maintenance as sm, skill_notes, skill_revisions

def _layout():
    return type("L", (), {"root": pathlib.Path(tempfile.mkdtemp())})()

def test_skill_score_from_notes():
    layout = _layout()
    for o in ("smooth", "smooth", "failed", "slow"):
        skill_notes.add_note(layout, skill="w", outcome=o, note="")
    s = sm.skill_score(layout, "w")
    assert s["uses"] == 4 and s["wins"] == 2 and abs(s["win_rate"] - 0.5) < 1e-9

def test_eligible_only_for_agent_owned():
    layout = _layout()
    # agent-owned: a self-improvement revision, no manual one
    skill_revisions.record(layout, skill="ag", version="v2", origin="self-improvement")
    assert sm._eligible_for_retire(layout, "ag") is True
    # user-touched: a manual revision → never eligible
    skill_revisions.record(layout, skill="usr", version="v2", origin="manual")
    assert sm._eligible_for_retire(layout, "usr") is False
    # untouched (no revisions) → not eligible (conservative)
    assert sm._eligible_for_retire(layout, "unknown") is False
```

- [ ] **Step 2: run → fail** (`no module skill_maintenance`).

- [ ] **Step 3: implement**

```python
"""Skill lifecycle — archive superseded versions, score skills from their
post-use notes, and retire (recoverably) agent-owned skills that never win.
Instance zone only; everything MOVES to ``.archive/`` (never deletes). See
dev/docs/process/SKILL_EVOLUTION_PLAN.md §6-§7."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from jaeger_os.core import skill_notes, skill_revisions

_VN = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)_v(?P<v>\d+)$")
ARCHIVE_DIR = ".archive"
_WIN = "smooth"


def skills_root(layout: Any) -> Path:
    return Path(layout.root) / "skills"


def skill_score(layout: Any, skill: str) -> dict:
    """uses / wins / win_rate from the post-use notes ('reviewing' markers
    don't count as uses; 'smooth' is a win)."""
    notes = [n for n in skill_notes.notes_for(layout, skill) if n.outcome != "reviewing"]
    uses = len(notes)
    wins = sum(1 for n in notes if n.outcome == _WIN)
    return {"uses": uses, "wins": wins,
            "win_rate": (wins / uses) if uses else 0.0}


def _eligible_for_retire(layout: Any, skill: str) -> bool:
    """Agent-owned only: at least one self-improvement revision AND no manual
    one. Untouched skills (no revisions) are never auto-retired."""
    revs = skill_revisions.revisions_for(layout, skill)
    if not revs:
        return False
    if any(r.origin == "manual" for r in revs):
        return False
    return any(r.origin == "self-improvement" for r in revs)
```

- [ ] **Step 4: run → pass.**  `.venv/bin/python -m pytest dev/tests/jaeger_os/core/test_skill_maintenance.py -v -k "score or eligible"`

- [ ] **Step 5: commit** (grouped at the §6/§7 milestone.)

---

### Task 2: Archive superseded versions

**Files:** Modify `skill_maintenance.py`; Test same file.

**Interfaces:**
- Produces: `archive_superseded_versions(layout, skill, *, keep=2) -> list[str]` (returns moved version folder names).

- [ ] **Step 1: failing test**

```python
def test_archive_keeps_top_k_and_hides_from_loader():
    from jaeger_os.agent.skill_registry import skill_loader
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))
    root = sm.skills_root(layout); root.mkdir(parents=True)
    for v in (1, 2, 3):
        d = root / f"w_v{v}"; d.mkdir()
        (d / "manifest.yaml").write_text(f"id: w\nversion: 0.{v}.0\n")
    moved = sm.archive_superseded_versions(layout, "w", keep=1)
    assert set(moved) == {"w_v1", "w_v2"}                 # only newest kept active
    assert (root / "w_v3").exists()
    assert (root / sm.ARCHIVE_DIR / "w_v1").exists()      # archived, recoverable
    assert not (root / "w_v1").exists()
    # the loader no longer discovers the archived versions
    names = {(s.name, s.version) for s in skill_loader._scan_zone(root, "instance")}
    assert ("w", 1) not in names and ("w", 2) not in names
```

- [ ] **Step 2: run → fail.**

- [ ] **Step 3: implement**

```python
def archive_superseded_versions(layout: Any, skill: str, *, keep: int = 2) -> list[str]:
    """Move all but the newest ``keep`` ``<skill>_vN`` dirs into ``.archive/``.
    Recoverable; the loader (direct-children + ``_v<N>`` match) never sees
    ``.archive/``."""
    root = skills_root(layout)
    if not root.is_dir():
        return []
    versions = []
    for child in root.iterdir():
        m = _VN.match(child.name)
        if child.is_dir() and m and m.group("name") == skill:
            versions.append((int(m.group("v")), child))
    versions.sort()                      # ascending; newest last
    superseded = versions[:-keep] if keep > 0 else versions
    archive = root / ARCHIVE_DIR
    archive.mkdir(exist_ok=True)
    moved = []
    for _v, d in superseded:
        dest = archive / d.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(d), str(dest))
        moved.append(d.name)
    return moved
```

- [ ] **Step 4: run → pass.**
- [ ] **Step 5: commit (grouped).**

---

### Task 3: Retire (recoverable, guarded)

**Files:** Modify `skill_maintenance.py`; Test same file.

**Interfaces:**
- Produces: `retire_candidates(layout, *, min_uses=5, max_win_rate=0.34) -> list[str]`; `retire(layout, skill) -> dict`.

- [ ] **Step 1: failing test**

```python
def test_retire_candidates_and_recoverable_move():
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))
    root = sm.skills_root(layout); (root / "bad_v1").mkdir(parents=True)
    (root / "bad_v1" / "manifest.yaml").write_text("id: bad\nversion: 0.1.0\n")
    # agent-owned + lots of failures → low win-rate → candidate
    skill_revisions.record(layout, skill="bad", version="v1", origin="self-improvement")
    for _ in range(6):
        skill_notes.add_note(layout, skill="bad", outcome="failed", note="")
    assert "bad" in sm.retire_candidates(layout, min_uses=5, max_win_rate=0.34)
    r = sm.retire(layout, "bad")
    assert r["retired"] is True
    assert (root / sm.ARCHIVE_DIR / "bad_v1").exists()    # recoverable
    assert not (root / "bad_v1").exists()

def test_user_skill_never_a_candidate():
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))
    skill_revisions.record(layout, skill="mine", version="v2", origin="manual")
    for _ in range(6):
        skill_notes.add_note(layout, skill="mine", outcome="failed", note="")
    assert "mine" not in sm.retire_candidates(layout, min_uses=5, max_win_rate=0.34)
```

- [ ] **Step 2: run → fail.**

- [ ] **Step 3: implement**

```python
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
    record the retirement as a revision. Refuses a non-eligible (user-owned)
    skill."""
    if not _eligible_for_retire(layout, skill):
        return {"retired": False, "reason": "not eligible (user-owned/untouched)"}
    root = skills_root(layout)
    archive = root / ARCHIVE_DIR
    archive.mkdir(parents=True, exist_ok=True)
    moved = []
    for child in list(root.iterdir()):
        m = _VN.match(child.name)
        if child.is_dir() and m and m.group("name") == skill:
            dest = archive / child.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(child), str(dest))
            moved.append(child.name)
    skill_revisions.record(layout, skill=skill, version="retired",
                           origin="self-improvement",
                           summary="retired: low win-rate", delta="")
    return {"retired": bool(moved), "moved": moved}
```

- [ ] **Step 4: run → pass.**
- [ ] **Step 5: commit (grouped).**

---

### Task 4: `maintenance_sweep` + idle wiring + `jaeger skills score`

**Files:** Modify `skill_maintenance.py`, `jaeger_os/main.py`, `jaeger_os/cli/skills_cmd.py`; Test in test_skill_maintenance.py + skills_cmd test.

**Interfaces:**
- Produces: `maintenance_sweep(layout, *, keep=2) -> dict` (`{archived: {skill:[...]}, retired: [...]}`).

- [ ] **Step 1: failing test**

```python
def test_maintenance_sweep_archives_and_retires(monkeypatch):
    from jaeger_os.core.instance.instance import InstanceLayout
    layout = InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))
    root = sm.skills_root(layout)
    for v in (1, 2, 3):
        (root / f"w_v{v}").mkdir(parents=True)
        (root / f"w_v{v}" / "manifest.yaml").write_text(f"id: w\nversion: 0.{v}.0\n")
    skill_revisions.record(layout, skill="w", version="v3", origin="self-improvement")
    for o in ("smooth", "smooth", "smooth"):                 # healthy → not retired
        skill_notes.add_note(layout, skill="w", outcome=o, note="")
    out = sm.maintenance_sweep(layout, keep=1)
    assert out["archived"]["w"] == ["w_v1", "w_v2"]
    assert "w" not in out["retired"]
```

- [ ] **Step 2: run → fail.**

- [ ] **Step 3: implement `maintenance_sweep`**

```python
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
```

- [ ] **Step 4: wire into the Deep-Think idle loop** — in `jaeger_os/main.py`, in the idle `while` loop right after the review `_sr.sweep(layout, queue)` block, add (low-frequency is fine; it's idempotent + recoverable):

```python
            try:
                from jaeger_os.core import skill_maintenance as _sm
                _sm.maintenance_sweep(layout)
            except Exception:  # noqa: BLE001 — maintenance never blocks deep-think
                pass
```

- [ ] **Step 5: add `jaeger skills score`** — in `jaeger_os/cli/skills_cmd.py`, add a `score` subcommand that prints each instance skill's `skill_score` + whether it's a retire candidate. (Mirror the existing `notes`/`revisions` subcommands.)

- [ ] **Step 6: run targeted + smoke** — `.venv/bin/python -m pytest dev/tests/jaeger_os/core/test_skill_maintenance.py -v`; `.venv/bin/python -c "import jaeger_os.main"`.

- [ ] **Step 7: commit (§6/§7 milestone)**

```bash
git add jaeger_os/core/skill_maintenance.py jaeger_os/main.py jaeger_os/cli/skills_cmd.py dev/tests/jaeger_os/core/test_skill_maintenance.py dev/docs/process/skill-evolution-impl-C-lifecycle.md
git commit -m "Skill evolution C: per-skill archive (§6) + scoring/retirement (§7), recoverable + guarded"
```

---

### Task 5: Gate + docs + full pipeline check

- [ ] **Step 1:** Full not-model gate — `.venv/bin/python -m pytest dev/tests -m "not model" -q`.
- [ ] **Step 2:** Mark §6/§7 shipped in `SKILL_EVOLUTION_PLAN.md` + STATUS entry; commit.
- [ ] **Step 3:** Full pipeline check (see below).

## Self-Review

- **Spec coverage:** §6 archive → T2; §7 scoring → T1, retirement → T3, schedule/wiring → T4 ✓.
- **Safety:** recoverable `.archive/` moves only; user-owned guard in `_eligible_for_retire` (T1) gates `retire`/`retire_candidates`; core zone untouched (instance `skills_root` only).
- **Type consistency:** `skill_score -> {uses,wins,win_rate}` used by `retire_candidates`; `_eligible_for_retire` gates both `retire_candidates` and `retire`; `_VN` regex mirrors the loader's `_SKILL_RE`; `maintenance_sweep` composes archive + retire.
