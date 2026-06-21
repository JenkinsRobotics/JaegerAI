"""Tests for the skill-tree registry — load/save, XP, level-up,
mastery cascade, prerequisite reconciliation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaeger_os.skill_tree import (
    SkillNode,
    SkillStatus,
    SkillTreeRegistry,
)


def _basic_node(skill_id: str, **kw) -> SkillNode:
    defaults = dict(
        id=skill_id,
        name=skill_id,
        category=skill_id.split(".")[0],
        xp_to_mastery=100,
    )
    defaults.update(kw)
    return SkillNode(**defaults)


# ── basic registration ─────────────────────────────────────────────

def test_register_skill_with_no_prereqs_is_available() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image"))
    node = reg.get("animation.image")
    assert node is not None
    assert node.status == SkillStatus.AVAILABLE


def test_register_skill_with_unmet_prereqs_is_locked() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node(
        "animation.sprite",
        prerequisites=("animation.image",),
    ))
    node = reg.get("animation.sprite")
    assert node is not None
    assert node.status == SkillStatus.LOCKED


def test_get_unknown_skill_returns_none() -> None:
    reg = SkillTreeRegistry.load()
    assert reg.get("does.not.exist") is None


# ── XP awards ──────────────────────────────────────────────────────

def test_award_xp_accumulates() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image"))
    reg.award_xp("animation.image", 5, reason="tool_call_success")
    reg.award_xp("animation.image", 3, reason="tool_call_success")
    node = reg.get("animation.image")
    assert node is not None
    assert node.xp == 8


def test_award_xp_to_unknown_skill_returns_none() -> None:
    reg = SkillTreeRegistry.load()
    assert reg.award_xp("does.not.exist", 5) is None


def test_award_xp_flips_available_to_active() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image"))
    reg.award_xp("animation.image", 1, reason="first_play")
    node = reg.get("animation.image")
    assert node is not None
    assert node.status == SkillStatus.ACTIVE


def test_award_xp_does_not_accept_non_positive() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image"))
    assert reg.award_xp("animation.image", 0) is None
    assert reg.award_xp("animation.image", -5) is None
    node = reg.get("animation.image")
    assert node is not None
    assert node.xp == 0


# ── level-up ───────────────────────────────────────────────────────

def test_xp_threshold_levels_up_within_skill() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node(
        "voice.tts",
        max_level=3,
        xp_to_next_level=50,
        xp_to_mastery=10_000,
    ))
    reg.award_xp("voice.tts", 60, reason="t")
    node = reg.get("voice.tts")
    assert node is not None
    assert node.level == 2


def test_single_huge_award_levels_up_multiple_times() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node(
        "voice.tts",
        max_level=5,
        xp_to_next_level=50,
        xp_to_mastery=10_000,
    ))
    reg.award_xp("voice.tts", 250, reason="milestone")
    node = reg.get("voice.tts")
    assert node is not None
    assert node.level == 5


# ── mastery + cascade ──────────────────────────────────────────────

def test_mastery_flips_status() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image", xp_to_mastery=50))
    reg.award_xp("animation.image", 60, reason="t")
    node = reg.get("animation.image")
    assert node is not None
    assert node.status == SkillStatus.MASTERED


def test_mastery_unlocks_child_when_prerequisites_met() -> None:
    reg = SkillTreeRegistry.load()
    parent = _basic_node(
        "animation.image",
        xp_to_mastery=50,
        unlocks=("animation.sprite",),
    )
    child = _basic_node(
        "animation.sprite",
        prerequisites=("animation.image",),
    )
    reg.register(parent)
    reg.register(child)
    assert reg.get("animation.sprite").status == SkillStatus.LOCKED
    reg.award_xp("animation.image", 100, reason="t")
    assert reg.get("animation.image").status == SkillStatus.MASTERED
    assert reg.get("animation.sprite").status == SkillStatus.AVAILABLE


def test_partial_prerequisites_keep_child_locked() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image", xp_to_mastery=10))
    reg.register(_basic_node("animation.sprite", xp_to_mastery=10))
    reg.register(_basic_node(
        "animation.gif",
        prerequisites=("animation.image", "animation.sprite"),
    ))
    reg.award_xp("animation.image", 20, reason="t")
    # Sprite hasn't been mastered yet; gif stays locked.
    assert reg.get("animation.gif").status == SkillStatus.LOCKED


# ── persistence ────────────────────────────────────────────────────

def test_save_then_load_round_trips_state(tmp_path: Path) -> None:
    persist = tmp_path / "skill_tree.json"
    reg = SkillTreeRegistry.load(persist_path=persist)
    reg.register(_basic_node(
        "animation.image",
        xp_to_mastery=100,
        unlocks=("animation.sprite",),
    ))
    reg.register(_basic_node(
        "animation.sprite",
        prerequisites=("animation.image",),
    ))
    reg.award_xp("animation.image", 60, reason="t")
    reg.save()

    reloaded = SkillTreeRegistry.load(persist_path=persist)
    assert reloaded.get("animation.image").xp == 60
    assert reloaded.get("animation.image").status == SkillStatus.ACTIVE
    assert reloaded.get("animation.sprite").status == SkillStatus.LOCKED


def test_corrupted_state_is_quarantined_not_crashed(
    tmp_path: Path,
) -> None:
    """A corrupted skill_tree.json shouldn't break boot — the file
    gets renamed for forensic review and a fresh tree starts."""
    persist = tmp_path / "skill_tree.json"
    persist.write_text("{ this is not valid msgspec json }")
    reg = SkillTreeRegistry.load(persist_path=persist)
    # Fresh tree (no skills).
    assert reg.all() == ()
    # Corrupted file renamed.
    assert (tmp_path / "skill_tree.json.bad").exists()


# ── logging ────────────────────────────────────────────────────────

def test_award_xp_appends_to_log(tmp_path: Path) -> None:
    log = tmp_path / "skill_tree.log"
    reg = SkillTreeRegistry.load(log_path=log)
    reg.register(_basic_node("animation.image"))
    reg.award_xp("animation.image", 5, reason="first_play",
                 metadata={"tool": "play_animation"})
    reg.award_xp("animation.image", 3, reason="tool_call_success")
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["skill_id"] == "animation.image"
    assert rec0["amount"] == 5
    assert rec0["reason"] == "first_play"
    assert rec0["metadata"]["tool"] == "play_animation"


# ── listener notifications ─────────────────────────────────────────

def test_listeners_receive_xp_and_mastery_events() -> None:
    reg = SkillTreeRegistry.load()
    events: list[tuple] = []
    reg.add_listener(lambda kind, payload: events.append((kind, payload)))
    reg.register(_basic_node(
        "animation.image",
        xp_to_mastery=50,
        unlocks=("animation.sprite",),
    ))
    reg.register(_basic_node(
        "animation.sprite",
        prerequisites=("animation.image",),
    ))
    reg.award_xp("animation.image", 100, reason="t")
    kinds = [k for (k, _) in events]
    assert "xp_awarded" in kinds
    assert "mastered" in kinds
    assert "unlocked" in kinds


def test_listener_exception_does_not_break_state_update() -> None:
    reg = SkillTreeRegistry.load()
    reg.register(_basic_node("animation.image"))
    reg.add_listener(lambda kind, payload: (_ for _ in ()).throw(
        RuntimeError("broken listener"),
    ))
    # Should not raise.
    reg.award_xp("animation.image", 5, reason="t")
    assert reg.get("animation.image").xp == 5
