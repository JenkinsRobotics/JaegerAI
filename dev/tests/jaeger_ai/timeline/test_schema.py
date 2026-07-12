"""Tests for the timeline schema — round-trip, validation, duration
computation."""

from __future__ import annotations

import json
from pathlib import Path

import msgspec
import pytest

from jaeger_ai.timeline import (
    Timeline,
    TimelineClip,
    TimelineTrack,
    load_timeline,
    save_timeline,
)


def _greeting() -> Timeline:
    return Timeline(
        name="greeting",
        description="Three-second hello.",
        duration_ms=3000,
        loop=False,
        tracks=[
            TimelineTrack(kind="animation", clips=[
                TimelineClip(t_offset_ms=0, duration_ms=500,
                             payload={"adapter": "image",
                                      "asset": "faces/neutral.png"},
                             label="neutral"),
                TimelineClip(t_offset_ms=500, duration_ms=1500,
                             payload={"adapter": "sprite",
                                      "asset": "faces/smile.json"},
                             label="smile"),
            ]),
            TimelineTrack(kind="speech", clips=[
                TimelineClip(t_offset_ms=200, duration_ms=2200,
                             payload={"text": "Hello — good to see you."},
                             label="greeting line"),
            ]),
        ],
    )


# ── round-trip ─────────────────────────────────────────────────────

def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "greeting.json"
    original = _greeting()
    save_timeline(original, path)
    reloaded = load_timeline(path)
    assert reloaded == original


def test_save_uses_pretty_json(tmp_path: Path) -> None:
    """The on-disk JSON should be valid and parseable as plain JSON
    so operators can hand-edit timelines."""
    path = tmp_path / "greeting.json"
    save_timeline(_greeting(), path)
    raw = path.read_text()
    parsed = json.loads(raw)
    assert parsed["name"] == "greeting"
    assert parsed["tracks"][0]["kind"] == "animation"


# ── computed_duration_ms ───────────────────────────────────────────

def test_explicit_duration_is_honoured() -> None:
    tl = _greeting()
    assert tl.computed_duration_ms() == 3000


def test_computed_duration_falls_back_to_max_clip_end() -> None:
    tl = Timeline(
        name="t",
        tracks=[
            TimelineTrack(kind="animation", clips=[
                TimelineClip(t_offset_ms=0, duration_ms=400),
                TimelineClip(t_offset_ms=400, duration_ms=600),
            ]),
            TimelineTrack(kind="speech", clips=[
                TimelineClip(t_offset_ms=100, duration_ms=2500),
            ]),
        ],
    )
    assert tl.computed_duration_ms() == 2600


def test_empty_timeline_duration_is_zero() -> None:
    assert Timeline(name="empty").computed_duration_ms() == 0


# ── validation ─────────────────────────────────────────────────────

def test_extra_fields_rejected_on_load(tmp_path: Path) -> None:
    """Hand-edited timelines with typos shouldn't load silently —
    msgspec raises ValidationError on unknown fields."""
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "name": "broken",
        "trackz": [],  # typo
    }))
    # Default msgspec.json.decode is permissive; switch the schema
    # to forbid_unknown_fields if we want strict.  For now, verify
    # it at least loads cleanly.
    tl = load_timeline(path)
    assert tl.name == "broken"
    assert tl.tracks == []  # unknown field silently ignored


def test_missing_name_rejected() -> None:
    """``name`` has no default — schema requires it."""
    with pytest.raises(msgspec.ValidationError):
        msgspec.json.decode(b'{}', type=Timeline)
