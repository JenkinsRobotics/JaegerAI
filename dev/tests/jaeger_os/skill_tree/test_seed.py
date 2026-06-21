"""Tests for the default skill-tree catalog — verifies the seed
function loads the expected categories + that the dependency graph
is well-formed (no orphaned prereq references, no cycles).
"""

from __future__ import annotations

import pytest

from jaeger_os.skill_tree import (
    SkillStatus,
    SkillTreeRegistry,
    default_catalog,
    seed_default_tree,
)


# ── catalog coverage ──────────────────────────────────────────────

def test_catalog_covers_expected_categories() -> None:
    cats = {n.category for n in default_catalog()}
    assert "animation" in cats
    assert "voice" in cats
    assert "vision" in cats
    assert "motor" in cats
    assert "light" in cats
    assert "core" in cats


def test_catalog_has_no_duplicate_ids() -> None:
    ids = [n.id for n in default_catalog()]
    assert len(ids) == len(set(ids))


def test_catalog_animation_levels_are_chained() -> None:
    """L1 image unlocks sprite (L2) which unlocks gif (L3) which
    unlocks video (L4)."""
    by_id = {n.id: n for n in default_catalog()}
    assert "animation.sprite" in by_id["animation.image"].unlocks
    assert by_id["animation.sprite"].prerequisites == ("animation.image",)
    assert "animation.gif" in by_id["animation.sprite"].unlocks
    assert by_id["animation.gif"].prerequisites == ("animation.sprite",)
    assert "animation.video" in by_id["animation.gif"].unlocks


def test_catalog_prereq_graph_has_no_orphans() -> None:
    """Every prereq references an id that exists in the catalog."""
    by_id = {n.id: n for n in default_catalog()}
    for node in default_catalog():
        for pid in node.prerequisites:
            assert pid in by_id, (
                f"{node.id} prereq {pid!r} doesn't exist in catalog"
            )
        for uid in node.unlocks:
            assert uid in by_id, (
                f"{node.id} unlocks {uid!r} which doesn't exist"
            )


def test_catalog_prereq_graph_is_acyclic() -> None:
    """No skill should be reachable from itself via prereqs."""
    by_id = {n.id: n for n in default_catalog()}

    def reachable_from(start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            node_id = stack.pop()
            for prereq in by_id[node_id].prerequisites:
                if prereq in seen:
                    continue
                seen.add(prereq)
                stack.append(prereq)
        return seen

    for node in default_catalog():
        reach = reachable_from(node.id)
        assert node.id not in reach, (
            f"cycle through {node.id}"
        )


# ── seed function ─────────────────────────────────────────────────

def test_seed_fills_empty_registry() -> None:
    reg = SkillTreeRegistry.load()
    seed_default_tree(reg)
    assert len(reg.all()) == len(default_catalog())


def test_seed_preserves_existing_xp() -> None:
    """Re-seeding shouldn't reset XP — operator's earned progress
    must survive."""
    reg = SkillTreeRegistry.load()
    seed_default_tree(reg)
    reg.award_xp("animation.image", 50, reason="test")
    seed_default_tree(reg)  # re-seed
    assert reg.get("animation.image").xp == 50


def test_seed_initial_statuses_respect_prereqs() -> None:
    reg = SkillTreeRegistry.load()
    seed_default_tree(reg)
    # animation.image has no prereqs → AVAILABLE
    assert reg.get("animation.image").status == SkillStatus.AVAILABLE
    # animation.gif requires sprite mastered → LOCKED
    assert reg.get("animation.gif").status == SkillStatus.LOCKED
    # voice.tts has no prereqs → AVAILABLE
    assert reg.get("voice.tts").status == SkillStatus.AVAILABLE


def test_seed_then_master_cascade() -> None:
    """End-to-end: master sprite + image → gif becomes available
    (matches the operator's intuition for L1→L2→L3 climb)."""
    reg = SkillTreeRegistry.load()
    seed_default_tree(reg)
    # Master image (200 XP).
    reg.award_xp("animation.image", 200, reason="lots_of_use")
    assert reg.get("animation.image").status == SkillStatus.MASTERED
    # Sprite should now be available; master it too (300 XP).
    assert reg.get("animation.sprite").status == SkillStatus.AVAILABLE
    reg.award_xp("animation.sprite", 300, reason="lots_of_use")
    assert reg.get("animation.sprite").status == SkillStatus.MASTERED
    # Now gif unlocks.
    assert reg.get("animation.gif").status == SkillStatus.AVAILABLE
