"""Tests for the AnimationNode — adapter dispatch, frame emission,
XP awarding, stop handling.

Uses a mock adapter so we exercise the Bus + node + skill-tree
contract without real Mochi-style decoding.  Live integration with
vendored Mochi handlers lands as a separate concrete test pass.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest

from jaeger_os.transport import topics
from jaeger_os.nodes.animation import AnimationNode, FrameBuffer
from jaeger_os.skill_tree import SkillNode, SkillTreeRegistry
from jaeger_os.transport import InProcBus


# ── fake adapter ──────────────────────────────────────────────────

@dataclass
class _FakeAdapter:
    skill_id: str = "animation.fake"
    level: int = 1
    name: str = "fake"
    frames_per_play: int = 3

    def __post_init__(self) -> None:
        self.opens: list[tuple[str, dict]] = []
        self.closes: int = 0
        self.frame_idx: int = 0

    def open(self, asset_path, *, width, height, params):
        self.opens.append((asset_path, dict(params)))
        self.frame_idx = 0

    def close(self):
        self.closes += 1

    def next_frame(self, t):
        if self.frame_idx >= self.frames_per_play:
            return None
        self.frame_idx += 1
        is_final = self.frame_idx == self.frames_per_play
        return FrameBuffer(
            width=4, height=4,
            data=bytes([self.frame_idx] * 4 * 4 * 4),
            duration_ms=10,
            is_final=is_final,
        )


# ── fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


def _registry_with_fake() -> SkillTreeRegistry:
    reg = SkillTreeRegistry.load()
    reg.register(SkillNode(
        id="animation.fake",
        name="fake adapter",
        category="animation",
        xp_to_mastery=100,
    ))
    return reg


def _start_node(bus, **kwargs):
    node = AnimationNode(bus=bus, **kwargs)
    thread = threading.Thread(target=node.run, daemon=True)
    thread.start()
    time.sleep(0.1)
    return node, thread


def _stop_node(node, thread):
    node.stop()
    thread.join(timeout=2.0)


# ── basic dispatch ────────────────────────────────────────────────

def test_command_routes_to_named_adapter(bus):
    adapter = _FakeAdapter()
    captured: list[FrameBuffer] = []
    node, thread = _start_node(
        bus,
        frame_callback=lambda f: captured.append(f),
    )
    node.register_adapter("fake", adapter)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="fake", asset_path="/tmp/whatever.png",
            params={"width": 4, "height": 4},
        ))
        # Give the node thread time to drain + stream.
        for _ in range(40):
            if adapter.closes > 0:
                break
            time.sleep(0.05)
        assert adapter.opens
        assert adapter.opens[0][0] == "/tmp/whatever.png"
        # Frames should have been emitted up to the natural end.
        assert len(captured) == adapter.frames_per_play
        assert captured[-1].is_final
    finally:
        _stop_node(node, thread)


def test_unknown_adapter_is_logged_not_raised(bus):
    captured: list[FrameBuffer] = []
    node, thread = _start_node(
        bus,
        frame_callback=lambda f: captured.append(f),
    )
    try:
        bus.publish(topics.AnimationCommand(
            adapter="nonexistent", asset_path="/tmp/x.png",
        ))
        time.sleep(0.3)
        assert captured == []
    finally:
        _stop_node(node, thread)


# ── XP awarding ────────────────────────────────────────────────────

def test_successful_play_awards_xp_to_adapter_skill(bus):
    adapter = _FakeAdapter()
    reg = _registry_with_fake()
    node, thread = _start_node(bus, skill_registry=reg)
    node.register_adapter("fake", adapter)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="fake", asset_path="/tmp/whatever.png",
            params={"width": 4, "height": 4},
        ))
        for _ in range(40):
            if reg.get("animation.fake").xp > 0:
                break
            time.sleep(0.05)
        assert reg.get("animation.fake").xp == 1
    finally:
        _stop_node(node, thread)


# ── stop handling ─────────────────────────────────────────────────

def test_animation_stop_interrupts_streaming(bus):
    adapter = _FakeAdapter(frames_per_play=100)
    captured: list[FrameBuffer] = []
    node, thread = _start_node(
        bus,
        frame_callback=lambda f: captured.append(f),
    )
    node.register_adapter("fake", adapter)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="fake", asset_path="/tmp/x.png",
            params={"width": 4, "height": 4},
        ))
        time.sleep(0.05)
        bus.publish(topics.AnimationStop())
        for _ in range(20):
            if adapter.closes > 0:
                break
            time.sleep(0.05)
        # We should have captured FAR fewer frames than the 100
        # the adapter would have produced uninterrupted.
        assert 0 < len(captured) < 100
    finally:
        _stop_node(node, thread)


# ── state publication ─────────────────────────────────────────────

def test_animation_state_published_for_play_then_idle(bus):
    adapter = _FakeAdapter(frames_per_play=2)
    captured_state: list[topics.TopicMessage] = []
    bus.subscribe(
        topics.SENSE_ANIMATION_STATE,
        lambda msg: captured_state.append(msg),
    )
    node, thread = _start_node(bus)
    node.register_adapter("fake", adapter)
    try:
        bus.publish(topics.AnimationCommand(
            adapter="fake", asset_path="/tmp/x.png",
            params={"width": 4, "height": 4},
        ))
        for _ in range(40):
            if any(s.state == "idle" for s in captured_state):
                break
            time.sleep(0.05)
        states = [s.state for s in captured_state]
        assert "playing" in states
        assert "idle" in states
    finally:
        _stop_node(node, thread)
