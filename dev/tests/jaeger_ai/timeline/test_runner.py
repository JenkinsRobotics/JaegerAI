"""Tests for the TimelineRunner — wall-clock multi-track scheduling.

Uses InProcBus + captured-event subscribers so we verify the actual
dispatched messages without firing up nodes.
"""

from __future__ import annotations

import time

import pytest

from jaeger_os.transport import topics
from jaeger_ai.timeline import (
    Timeline,
    TimelineClip,
    TimelineRunner,
    TimelineTrack,
    parse_timeline_json,
)
from jaeger_os.transport import InProcBus


@pytest.fixture
def bus():
    b = InProcBus()
    yield b
    b.close()


# ── empty timeline ────────────────────────────────────────────────

def test_empty_timeline_completes_immediately(bus) -> None:
    progress: list[topics.TopicMessage] = []
    bus.subscribe(
        topics.SENSE_TIMELINE_PROGRESS,
        lambda msg: progress.append(msg),
    )
    runner = TimelineRunner(bus, Timeline(name="empty"))
    runner.start()
    assert runner.wait(timeout=2.0)
    assert runner.final_state == "complete"
    # InProcBus delivery is queue-driven; give the delivery thread a
    # tick to drain after the runner finishes.
    for _ in range(20):
        if {"running", "complete"} <= {m.state for m in progress}:
            break
        time.sleep(0.05)
    states = [m.state for m in progress]
    assert "running" in states
    assert "complete" in states


# ── animation track dispatch ──────────────────────────────────────

def test_animation_clips_dispatch_at_offsets(bus) -> None:
    received: list[topics.AnimationCommand] = []
    bus.subscribe(
        topics.ACT_ANIMATION,
        lambda msg: received.append(msg),
    )
    tl = Timeline(name="anim", tracks=[
        TimelineTrack(kind="animation", clips=[
            TimelineClip(t_offset_ms=0, duration_ms=100,
                         payload={"adapter": "image",
                                  "asset": "a.png"}),
            TimelineClip(t_offset_ms=100, duration_ms=100,
                         payload={"adapter": "gif",
                                  "asset": "b.gif"}),
        ]),
    ])
    runner = TimelineRunner(bus, tl)
    runner.start()
    assert runner.wait(timeout=3.0)
    # Both clips should have been dispatched.
    assert len(received) == 2
    assert received[0].adapter == "image"
    assert received[0].asset_path == "a.png"
    assert received[1].adapter == "gif"
    assert received[1].asset_path == "b.gif"


# ── speech track dispatch ─────────────────────────────────────────

def test_speech_clips_dispatch(bus) -> None:
    received: list[topics.SpeechCommand] = []
    bus.subscribe(topics.ACT_SPEECH, lambda msg: received.append(msg))
    tl = Timeline(name="speak", tracks=[
        TimelineTrack(kind="speech", clips=[
            TimelineClip(t_offset_ms=0, duration_ms=200,
                         payload={"text": "Hi there.",
                                  "voice": "am_michael"}),
        ]),
    ])
    runner = TimelineRunner(bus, tl)
    runner.start()
    assert runner.wait(timeout=2.0)
    assert len(received) == 1
    assert received[0].text == "Hi there."
    assert received[0].voice == "am_michael"


# ── unknown track kind silently skipped ───────────────────────────

def test_unknown_track_kind_does_not_break(bus) -> None:
    """Future-looking timelines with motion/light tracks should
    schedule for timing fidelity but not crash."""
    received_anim: list[topics.AnimationCommand] = []
    bus.subscribe(
        topics.ACT_ANIMATION,
        lambda msg: received_anim.append(msg),
    )
    tl = Timeline(name="mixed", tracks=[
        TimelineTrack(kind="motion", clips=[
            TimelineClip(t_offset_ms=0, duration_ms=50,
                         payload={"linear_x": 0.1}),
        ]),
        TimelineTrack(kind="animation", clips=[
            TimelineClip(t_offset_ms=0, duration_ms=50,
                         payload={"adapter": "image",
                                  "asset": "a.png"}),
        ]),
    ])
    runner = TimelineRunner(bus, tl)
    runner.start()
    assert runner.wait(timeout=2.0)
    assert runner.final_state == "complete"
    # Animation dispatched; motion silently skipped.
    assert len(received_anim) == 1


# ── stop interrupts ───────────────────────────────────────────────

def test_stop_interrupts_mid_run(bus) -> None:
    progress: list[topics.TimelineProgress] = []
    bus.subscribe(
        topics.SENSE_TIMELINE_PROGRESS,
        lambda msg: progress.append(msg),
    )
    # 5-second timeline; we stop it after ~100 ms.
    tl = Timeline(name="long", tracks=[
        TimelineTrack(kind="animation", clips=[
            TimelineClip(t_offset_ms=4000, duration_ms=500,
                         payload={"adapter": "image",
                                  "asset": "way_later.png"}),
        ]),
    ])
    runner = TimelineRunner(bus, tl)
    runner.start()
    time.sleep(0.1)
    runner.stop()
    assert runner.wait(timeout=2.0)
    assert runner.final_state == "interrupted"
    for _ in range(20):
        if "interrupted" in [m.state for m in progress]:
            break
        time.sleep(0.05)
    states = [m.state for m in progress]
    assert "interrupted" in states


# ── clip ordering ─────────────────────────────────────────────────

def test_clips_dispatched_in_time_order(bus) -> None:
    """Even when authored out-of-order, clips fire at correct times."""
    received: list[topics.AnimationCommand] = []
    bus.subscribe(
        topics.ACT_ANIMATION,
        lambda msg: received.append(msg),
    )
    tl = Timeline(name="ordered", tracks=[
        TimelineTrack(kind="animation", clips=[
            # Authored late-first, early-second.
            TimelineClip(t_offset_ms=200, duration_ms=50,
                         payload={"adapter": "image", "asset": "B.png"}),
            TimelineClip(t_offset_ms=50, duration_ms=50,
                         payload={"adapter": "image", "asset": "A.png"}),
        ]),
    ])
    runner = TimelineRunner(bus, tl)
    runner.start()
    assert runner.wait(timeout=2.0)
    assert [c.asset_path for c in received] == ["A.png", "B.png"]


# ── inline-json parser ────────────────────────────────────────────

def test_parse_timeline_json_round_trips() -> None:
    payload = (
        '{"name":"x","tracks":[{"kind":"animation","clips":['
        '{"t_offset_ms":0,"duration_ms":100,'
        '"payload":{"adapter":"image","asset":"a.png"}}'
        ']}]}'
    )
    tl = parse_timeline_json(payload)
    assert tl.name == "x"
    assert len(tl.tracks) == 1
    assert tl.tracks[0].clips[0].payload["adapter"] == "image"
