"""Skill lifecycle — scoring, archive, retirement (Plan C §6-§7). Recoverable +
guarded: moves to .archive/, never deletes; never retires a user-written skill."""

import pathlib
import tempfile

from jaeger_ai.core.skill_improvement import skill_maintenance as sm, skill_notes, skill_revisions
from jaeger_ai.core.instance.instance import InstanceLayout


def _layout() -> InstanceLayout:
    return InstanceLayout(root=pathlib.Path(tempfile.mkdtemp()))


def _versioned_skill(layout, skill, versions) -> pathlib.Path:
    root = sm.skills_root(layout)
    root.mkdir(parents=True, exist_ok=True)
    for v in versions:
        d = root / f"{skill}_v{v}"
        d.mkdir()
        (d / "manifest.yaml").write_text(f"id: {skill}\nversion: 0.{v}.0\n")
    return root


# ── scoring + eligibility ──────────────────────────────────────────


def test_skill_score_from_notes() -> None:
    layout = _layout()
    for o in ("smooth", "smooth", "failed", "slow"):
        skill_notes.add_note(layout, skill="w", outcome=o, note="")
    s = sm.skill_score(layout, "w")
    assert s["uses"] == 4 and s["wins"] == 2 and abs(s["win_rate"] - 0.5) < 1e-9


def test_eligible_only_for_agent_owned() -> None:
    layout = _layout()
    skill_revisions.record(layout, skill="ag", version="v2", origin="self-improvement")
    assert sm._eligible_for_retire(layout, "ag") is True
    skill_revisions.record(layout, skill="usr", version="v2", origin="manual")
    assert sm._eligible_for_retire(layout, "usr") is False     # user-touched
    assert sm._eligible_for_retire(layout, "unknown") is False  # untouched


# ── archive ────────────────────────────────────────────────────────


def test_archive_keeps_top_k_and_hides_from_loader() -> None:
    from jaeger_ai.agent.skill_registry import skill_loader
    layout = _layout()
    root = _versioned_skill(layout, "w", (1, 2, 3))
    moved = sm.archive_superseded_versions(layout, "w", keep=1)
    assert set(moved) == {"w_v1", "w_v2"}                      # newest kept active
    assert (root / "w_v3").exists()
    assert (root / sm.ARCHIVE_DIR / "w_v1").exists()           # recoverable
    assert not (root / "w_v1").exists()
    names = {(s.name, s.version) for s in skill_loader._scan_zone(root, "instance")}
    assert ("w", 1) not in names and ("w", 2) not in names     # loader can't see them


# ── retirement (recoverable, guarded) ──────────────────────────────


def test_retire_candidates_and_recoverable_move() -> None:
    layout = _layout()
    root = _versioned_skill(layout, "bad", (1,))
    skill_revisions.record(layout, skill="bad", version="v1", origin="self-improvement")
    for _ in range(6):
        skill_notes.add_note(layout, skill="bad", outcome="failed", note="")
    assert "bad" in sm.retire_candidates(layout, min_uses=5, max_win_rate=0.34)
    r = sm.retire(layout, "bad")
    assert r["retired"] is True
    assert (root / sm.ARCHIVE_DIR / "bad_v1").exists()         # recoverable
    assert not (root / "bad_v1").exists()


def test_user_skill_never_a_candidate_or_retired() -> None:
    layout = _layout()
    _versioned_skill(layout, "mine", (1,))
    skill_revisions.record(layout, skill="mine", version="v2", origin="manual")
    for _ in range(6):
        skill_notes.add_note(layout, skill="mine", outcome="failed", note="")
    assert "mine" not in sm.retire_candidates(layout, min_uses=5, max_win_rate=0.34)
    assert sm.retire(layout, "mine")["retired"] is False       # refused
    assert (sm.skills_root(layout) / "mine_v1").exists()       # untouched


# ── the composed maintenance sweep ─────────────────────────────────


def test_maintenance_sweep_archives_and_keeps_healthy() -> None:
    layout = _layout()
    _versioned_skill(layout, "w", (1, 2, 3))
    skill_revisions.record(layout, skill="w", version="v3", origin="self-improvement")
    for _ in range(3):                                         # healthy → not retired
        skill_notes.add_note(layout, skill="w", outcome="smooth", note="")
    out = sm.maintenance_sweep(layout, keep=1)
    assert out["archived"]["w"] == ["w_v1", "w_v2"]
    assert "w" not in out["retired"]
