"""Skill Curator — keeps the agent-authored skill library from rotting.

Audit A2. The Curator's invariants are load-bearing: it must NEVER touch
a builtin / user / pinned skill, and it must NEVER delete — only move
into a reversible archive. The safety tests below are as important as the
behaviour tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jaeger_ai.agent.skill_registry import curator
from jaeger_ai.agent.skill_registry.playbook_skills import PlaybookSkill

_NOW = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)


def _days_ago(n: int) -> str:
    return (_NOW - timedelta(days=n)).isoformat(timespec="seconds")


def _make_skill(root, name, origin="agent", *, pinned=False) -> PlaybookSkill:
    """Create a real skill folder under ``root`` and return its PlaybookSkill."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\nbody\n",
        encoding="utf-8",
    )
    (folder / ".origin").write_text(origin + "\n", encoding="utf-8")
    if pinned:
        curator.pin_skill(folder)
    return PlaybookSkill(name=name, category="test",
                         description="test skill",
                         path=folder / "SKILL.md", origin=origin)


# ── pinning ─────────────────────────────────────────────────────────


def test_pin_unpin_roundtrip(tmp_path):
    folder = tmp_path / "s"
    folder.mkdir()
    assert curator.is_pinned(folder) is False
    curator.pin_skill(folder)
    assert curator.is_pinned(folder) is True
    curator.unpin_skill(folder)
    assert curator.is_pinned(folder) is False


# ── assess — classification ─────────────────────────────────────────


def test_builtin_skill_is_protected(tmp_path):
    s = _make_skill(tmp_path, "shipped", origin="builtin")
    [a] = curator.assess([s], usage={}, now=_NOW)
    assert a.status == "protected"


def test_user_skill_is_protected(tmp_path):
    s = _make_skill(tmp_path, "handwritten", origin="user")
    [a] = curator.assess([s], usage={}, now=_NOW)
    assert a.status == "protected"


def test_pinned_agent_skill_is_protected(tmp_path):
    s = _make_skill(tmp_path, "kept", origin="agent", pinned=True)
    usage = {"kept": {"last_used": _days_ago(999)}}
    [a] = curator.assess([s], usage=usage, now=_NOW)
    assert a.status == "protected"
    assert a.reason == "pinned"


def test_recently_used_agent_skill_is_active(tmp_path):
    s = _make_skill(tmp_path, "fresh", origin="agent")
    usage = {"fresh": {"last_used": _days_ago(3)}}
    [a] = curator.assess([s], usage=usage, now=_NOW)
    assert a.status == "active"


def test_idle_agent_skill_is_stale(tmp_path):
    s = _make_skill(tmp_path, "old", origin="agent")
    usage = {"old": {"last_used": _days_ago(60)}}
    [a] = curator.assess([s], usage=usage, now=_NOW)
    assert a.status == "stale"


def test_never_used_agent_skill_is_unused_not_stale(tmp_path):
    """A never-used agent skill might just be new — report it, do not
    auto-archive it."""
    s = _make_skill(tmp_path, "brandnew", origin="agent")
    [a] = curator.assess([s], usage={}, now=_NOW)
    assert a.status == "unused"


# ── run_curation — dry run vs apply ─────────────────────────────────


def test_dry_run_reports_but_moves_nothing(tmp_path):
    s = _make_skill(tmp_path / "skills", "old", origin="agent")
    usage = {"old": {"last_used": _days_ago(90)}}
    report = curator.run_curation(
        skills=[s], usage=usage, now=_NOW,
        archive_dir=tmp_path / "archive", apply=False,
    )
    assert report["dry_run"] is True
    assert len(report["stale"]) == 1
    assert report["archived"] == []
    assert s.path.parent.exists()        # folder untouched


def test_apply_archives_a_stale_agent_skill(tmp_path):
    s = _make_skill(tmp_path / "skills", "old", origin="agent")
    usage = {"old": {"last_used": _days_ago(90)}}
    archive = tmp_path / "archive"
    report = curator.run_curation(
        skills=[s], usage=usage, now=_NOW, archive_dir=archive, apply=True,
    )
    assert report["dry_run"] is False
    assert len(report["archived"]) == 1
    assert not s.path.parent.exists()    # moved out of the skills tree
    assert list(archive.rglob("SKILL.md"))   # …and into the archive


def test_apply_never_archives_a_builtin_skill(tmp_path):
    """The load-bearing invariant: a builtin skill is never moved, even
    if its usage looks ancient."""
    builtin = _make_skill(tmp_path / "skills", "shipped", origin="builtin")
    usage = {"shipped": {"last_used": _days_ago(999)}}
    curator.run_curation(
        skills=[builtin], usage=usage, now=_NOW,
        archive_dir=tmp_path / "archive", apply=True,
    )
    assert builtin.path.parent.exists()  # untouched


def test_apply_never_archives_a_pinned_skill(tmp_path):
    pinned = _make_skill(tmp_path / "skills", "kept",
                         origin="agent", pinned=True)
    usage = {"kept": {"last_used": _days_ago(999)}}
    curator.run_curation(
        skills=[pinned], usage=usage, now=_NOW,
        archive_dir=tmp_path / "archive", apply=True,
    )
    assert pinned.path.parent.exists()   # untouched


def test_apply_does_not_archive_never_used_skills(tmp_path):
    s = _make_skill(tmp_path / "skills", "brandnew", origin="agent")
    report = curator.run_curation(
        skills=[s], usage={}, now=_NOW,
        archive_dir=tmp_path / "archive", apply=True,
    )
    assert report["archived"] == []
    assert s.path.parent.exists()


# ── archive / restore round-trip ────────────────────────────────────


def test_archive_then_restore_brings_a_skill_back(tmp_path):
    s = _make_skill(tmp_path / "skills", "old", origin="agent")
    original = s.path.parent
    archive = tmp_path / "archive"

    curator.archive_skill(original, archive_dir=archive)
    assert not original.exists()

    listed = curator.list_archived(archive_dir=archive)
    assert [e["name"] for e in listed] == ["old"]

    result = curator.restore_skill("old", archive_dir=archive)
    assert result["ok"] is True
    assert original.exists()                       # back in place
    assert (original / "SKILL.md").exists()


def test_restore_refuses_to_overwrite_an_existing_folder(tmp_path):
    s = _make_skill(tmp_path / "skills", "old", origin="agent")
    original = s.path.parent
    archive = tmp_path / "archive"
    curator.archive_skill(original, archive_dir=archive)

    # A new skill takes the old slot — restore must not clobber it.
    original.mkdir(parents=True, exist_ok=True)
    result = curator.restore_skill("old", archive_dir=archive)
    assert result["ok"] is False


# ── smoke: real library, default args ───────────────────────────────


def test_run_curation_on_the_real_library_is_safe(tmp_path):
    """A default dry run over the shipped library must not raise and
    must archive nothing (every shipped skill is builtin → protected)."""
    report = curator.run_curation(apply=False)
    assert report["ok"] is True
    assert report["dry_run"] is True
    assert report["archived"] == []
