"""A timeline is a performance: many tracks, one wall clock.

Salvaged from Mochi v4, where it shipped with no tests. These are the
properties worth holding on to — scheduling order, the two dispatches
that are wired, and the three that are deliberately not.
"""

from __future__ import annotations

import time

import msgspec
import pytest

from jaeger_os.contract import topics
from jaeger_os.timeline import (
    TRACK_ANIMATION,
    TRACK_LIGHT,
    TRACK_SPEECH,
    Timeline,
    TimelineClip,
    TimelineRunner,
    TimelineTrack,
    load_timeline,
    parse_timeline_json,
    save_timeline,
)


class _RecordingBus:
    """Enough Bus to see what a timeline puts on it."""

    def __init__(self) -> None:
        self.published: list = []

    def publish(self, message) -> None:
        self.published.append(message)


def _timeline(**kwargs) -> Timeline:
    return Timeline(
        name="greeting",
        tracks=[
            TimelineTrack(kind=TRACK_ANIMATION, clips=[
                TimelineClip(t_offset_ms=0, duration_ms=40,
                             payload={"asset": "wave.gif"}),
            ]),
            TimelineTrack(kind=TRACK_SPEECH, clips=[
                TimelineClip(t_offset_ms=20, payload={"text": "hello"}),
            ]),
        ],
        **kwargs,
    )


# ── the schema ───────────────────────────────────────────────────

def test_duration_is_computed_from_the_tracks_when_unset():
    """0 means "as long as it takes", so a author who adds a clip does
    not also have to remember to extend the total."""
    assert _timeline().computed_duration_ms() == 40
    assert _timeline(duration_ms=5000).computed_duration_ms() == 5000
    assert Timeline(name="empty").computed_duration_ms() == 0


def test_a_timeline_round_trips_through_disk(tmp_path):
    path = tmp_path / "timelines" / "greeting.json"
    save_timeline(_timeline(), path)
    assert path.is_file()
    loaded = load_timeline(path)
    assert loaded.name == "greeting"
    assert [t.kind for t in loaded.tracks] == [TRACK_ANIMATION, TRACK_SPEECH]
    assert loaded.tracks[1].clips[0].payload["text"] == "hello"


def test_a_malformed_timeline_refuses_rather_than_half_loading(tmp_path):
    """A precise error beats a Timeline missing the track someone
    thought they wrote."""
    path = tmp_path / "broken.json"
    path.write_text('{"name": "x", "tracks": [{"clips": []}]}')
    with pytest.raises(msgspec.ValidationError):
        load_timeline(path)


def test_inline_json_is_the_same_schema_as_the_file():
    """TimelineCommand carries a timeline inline OR by name; both have
    to mean the same thing or the wire format has two dialects."""
    inline = parse_timeline_json(msgspec.json.encode(_timeline()).decode())
    assert inline.computed_duration_ms() == 40


# ── the runner ───────────────────────────────────────────────────

def test_clips_dispatch_in_time_order_across_tracks():
    """The point of a timeline: tracks are authored separately and
    played interleaved. Animation at 0ms must precede speech at 20ms
    even though it is a different track."""
    bus = _RecordingBus()
    runner = TimelineRunner(bus, _timeline())
    runner.start()
    assert runner.wait(timeout=5.0), "the runner never finished"

    kinds = [type(m).__name__ for m in bus.published]
    assert kinds[0] == "TimelineProgress"
    assert kinds[1:3] == ["DisplayCommand", "SpeechCommand"]
    assert bus.published[1].asset_path == "wave.gif"
    assert bus.published[1].adapter == "auto"
    assert bus.published[2].text == "hello"
    # Empty voice = the module's configured default. Naming one here
    # would override every character's own voice from a timeline that
    # has no opinion about it.
    assert bus.published[2].voice == ""
    assert runner.final_state == "complete"
    assert bus.published[-1].state == "complete"


def test_unwired_track_kinds_keep_time_without_dispatching():
    """sound / motion / light have no nodes yet. A timeline that uses
    them must still play its other tracks at the right moments, or
    authoring ahead of the hardware is impossible."""
    bus = _RecordingBus()
    timeline = Timeline(name="future", tracks=[
        TimelineTrack(kind=TRACK_LIGHT, clips=[
            TimelineClip(t_offset_ms=0, payload={"rgb": [255, 0, 0]})]),
        TimelineTrack(kind=TRACK_SPEECH, clips=[
            TimelineClip(t_offset_ms=10, payload={"text": "still on time"})]),
    ])
    runner = TimelineRunner(bus, timeline)
    runner.start()
    assert runner.wait(timeout=5.0)
    speech = [m for m in bus.published if type(m).__name__ == "SpeechCommand"]
    assert [m.text for m in speech] == ["still on time"]
    assert runner.final_state == "complete"


def test_stopping_mid_timeline_says_interrupted():
    """A performance cut short is a different outcome from one that
    ended, and the brain is told which."""
    bus = _RecordingBus()
    timeline = Timeline(name="long", tracks=[
        TimelineTrack(kind=TRACK_SPEECH, clips=[
            TimelineClip(t_offset_ms=0, payload={"text": "first"}),
            TimelineClip(t_offset_ms=60_000, payload={"text": "never"}),
        ]),
    ])
    runner = TimelineRunner(bus, timeline)
    runner.start()
    time.sleep(0.2)
    runner.stop()
    assert runner.wait(timeout=5.0), "stop() did not end the runner"
    assert runner.final_state == "interrupted"
    assert [m.text for m in bus.published
            if type(m).__name__ == "SpeechCommand"] == ["first"]
    assert bus.published[-1].state == "interrupted"


def test_a_publish_that_raises_interrupts_instead_of_wedging():
    """The scheduler thread is a daemon nobody is watching. An
    exception mid-clip has to end the timeline and SAY so, not die
    silently holding the done event forever."""
    class _AngryBus(_RecordingBus):
        def publish(self, message):
            if type(message).__name__ == "SpeechCommand":
                raise RuntimeError("no speech node")
            super().publish(message)

    bus = _AngryBus()
    runner = TimelineRunner(bus, _timeline())
    runner.start()
    assert runner.wait(timeout=5.0), "the runner hung on a failed publish"
    assert runner.final_state == "interrupted"


def test_the_topics_it_publishes_are_the_declared_contract():
    """The implementation was salvaged; the contract never left. If
    these drift apart the topics are declared and unrunnable again."""
    assert topics.TimelineCommand().topic == topics.ACT_TIMELINE_RUN
    assert topics.TimelineProgress().topic == topics.ACT_TIMELINE_PROGRESS
    bus = _RecordingBus()
    runner = TimelineRunner(bus, Timeline(name="empty"))
    runner.start()
    assert runner.wait(timeout=5.0)
    assert {m.topic for m in bus.published} == {topics.ACT_TIMELINE_PROGRESS}
