"""Tests for the XpEmitter — bus integration for the skill-tree
registry."""

from __future__ import annotations

import time

import pytest

from jaeger_os.transport import topics
from jaeger_os.skill_tree import (
    SkillNode,
    SkillStatus,
    SkillTreeRegistry,
    XpEmitter,
    award_xp,
)
from jaeger_os.transport import InProcBus


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _make_registry() -> SkillTreeRegistry:
    reg = SkillTreeRegistry.load()
    reg.register(SkillNode(
        id="animation.image",
        name="Image",
        category="animation",
        xp_to_mastery=50,
        unlocks=("animation.sprite",),
    ))
    reg.register(SkillNode(
        id="animation.sprite",
        name="Sprite",
        category="animation",
        prerequisites=("animation.image",),
        xp_to_mastery=50,
    ))
    return reg


def _wait_for(predicate, *, timeout: float = 1.0,
              interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ── bus → registry ────────────────────────────────────────────────

def test_xp_awarded_event_grants_to_registry(bus) -> None:
    registry = _make_registry()
    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()
    try:
        award_xp(bus, "animation.image", 5, reason="tool_call_success")
        ok = _wait_for(lambda: registry.get("animation.image").xp >= 5)
        assert ok, "XP grant didn't reach the registry"
        assert registry.get("animation.image").xp == 5
    finally:
        emitter.stop()


def test_xp_award_to_unknown_skill_is_noop(bus) -> None:
    """An XP event for an unregistered skill is silently dropped —
    the registry doesn't crash and no level-up cascades happen."""
    registry = _make_registry()
    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()
    try:
        award_xp(bus, "does.not.exist", 100, reason="t")
        # Give the bus a moment to dispatch.
        time.sleep(0.1)
        # Registered skills should be unchanged.
        assert registry.get("animation.image").xp == 0
    finally:
        emitter.stop()


# ── registry → bus ────────────────────────────────────────────────

def test_mastery_publishes_skill_mastered(bus) -> None:
    registry = _make_registry()
    mastered: list[str] = []
    unlocked: list[str] = []
    bus.subscribe(
        topics.SENSE_SKILL_MASTERED,
        lambda msg: mastered.append(msg.skill_id),
    )
    bus.subscribe(
        topics.SENSE_SKILL_UNLOCKED,
        lambda msg: unlocked.append(msg.skill_id),
    )
    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()
    try:
        award_xp(bus, "animation.image", 100, reason="t")
        ok = _wait_for(lambda: "animation.image" in mastered)
        assert ok, "skill_mastered event never fired"
        # Cascade — sprite should also be unlocked now.
        ok = _wait_for(lambda: "animation.sprite" in unlocked)
        assert ok
        assert registry.get("animation.image").status == SkillStatus.MASTERED
        assert registry.get("animation.sprite").status == SkillStatus.AVAILABLE
    finally:
        emitter.stop()


def test_level_up_publishes_skill_level_up(bus) -> None:
    registry = SkillTreeRegistry.load()
    registry.register(SkillNode(
        id="voice.tts",
        name="TTS",
        category="voice",
        max_level=3,
        xp_to_next_level=30,
        xp_to_mastery=10_000,
    ))
    level_ups: list[int] = []
    bus.subscribe(
        topics.SENSE_SKILL_LEVEL_UP,
        lambda msg: level_ups.append(msg.new_level),
    )
    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()
    try:
        award_xp(bus, "voice.tts", 40, reason="t")
        ok = _wait_for(lambda: 2 in level_ups)
        assert ok, "level_up event never fired"
    finally:
        emitter.stop()


# ── lifecycle ─────────────────────────────────────────────────────

def test_start_is_idempotent(bus) -> None:
    registry = _make_registry()
    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()
    emitter.start()  # idempotent
    award_xp(bus, "animation.image", 5)
    ok = _wait_for(lambda: registry.get("animation.image").xp == 5)
    assert ok
    emitter.stop()


def test_stop_is_idempotent(bus) -> None:
    registry = _make_registry()
    emitter = XpEmitter(bus=bus, registry=registry)
    emitter.start()
    emitter.stop()
    emitter.stop()  # idempotent
