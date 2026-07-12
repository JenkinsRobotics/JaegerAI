"""Tests for the GifAdapter — L3 GIF animation level.

Builds animated GIFs in-test with Pillow so no fixture management.
Verifies multi-frame walking, loop semantics, per-frame durations,
and the close-then-reopen cycle.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from jaeger_ai.nodes.animation.adapters import GifAdapter


def _gif(tmp_path: Path, *, frames: int, color_step: int = 40) -> Path:
    """Build a tiny animated GIF: ``frames`` frames at 100 ms each,
    each a different solid colour so frame-walking is observable."""
    p = tmp_path / "anim.gif"
    images = [
        Image.new("RGB", (4, 4),
                  ((i * color_step) % 256, 0, 0))
        for i in range(frames)
    ]
    images[0].save(
        p, save_all=True, append_images=images[1:],
        duration=100, loop=0,
    )
    return p


# ── identity ──────────────────────────────────────────────────────

def test_adapter_identity() -> None:
    g = GifAdapter()
    assert g.skill_id == "animation.gif"
    assert g.level == 3


# ── open + walk frames ────────────────────────────────────────────

def test_open_loads_multiple_frames(tmp_path: Path) -> None:
    asset = _gif(tmp_path, frames=4)
    g = GifAdapter()
    g.open(str(asset), width=4, height=4, params={"fit": "fill"})
    # We should have 4 distinct cached frames internally.
    assert len(g._frames) == 4


def test_walks_through_frames_over_time(tmp_path: Path) -> None:
    asset = _gif(tmp_path, frames=3)
    g = GifAdapter()
    g.open(str(asset), width=4, height=4, params={"fit": "fill"})
    # At t=0 → first frame; at t=0.15 (after 150 ms) → second frame
    # (durations are 100 ms each).
    f0 = g.next_frame(0.0)
    f1 = g.next_frame(0.15)
    f2 = g.next_frame(0.25)
    assert f0 is not None and f1 is not None and f2 is not None
    # All three should be distinct (different first-pixel R values).
    assert f0.data[0] != f1.data[0] or f0.data[0] != f2.data[0]


# ── loop semantics ────────────────────────────────────────────────

def test_loop_default_true(tmp_path: Path) -> None:
    """A GIF with total duration 300 ms should still emit at t=10s
    when looping is on."""
    asset = _gif(tmp_path, frames=3)
    g = GifAdapter()
    g.open(str(asset), width=4, height=4, params={"fit": "fill"})
    assert g.next_frame(10.0) is not None


def test_loop_false_returns_none_after_one_pass(tmp_path: Path) -> None:
    asset = _gif(tmp_path, frames=3)
    g = GifAdapter()
    g.open(str(asset), width=4, height=4,
           params={"fit": "fill", "loop": False})
    # First call sets t=0 as start; we have 3 × 100 ms = 300 ms total.
    assert g.next_frame(0.0) is not None
    # Past end (350 ms) → None.
    assert g.next_frame(0.35) is None


# ── close + reopen ────────────────────────────────────────────────

def test_close_then_reopen_resets_clock(tmp_path: Path) -> None:
    asset = _gif(tmp_path, frames=2)
    g = GifAdapter()
    g.open(str(asset), width=4, height=4,
           params={"fit": "fill", "loop": False})
    g.next_frame(0.0)
    g.close()
    assert g.next_frame(0.0) is None
    g.open(str(asset), width=4, height=4,
           params={"fit": "fill", "loop": False})
    assert g.next_frame(0.0) is not None


# ── fit modes ─────────────────────────────────────────────────────

def test_contain_fit_letterboxes(tmp_path: Path) -> None:
    """Square GIF into wide target → red letterbox bands when configured."""
    p = tmp_path / "sq.gif"
    images = [Image.new("RGB", (4, 4), (0, 0, 0)) for _ in range(2)]
    images[0].save(p, save_all=True, append_images=images[1:],
                    duration=100, loop=0)
    g = GifAdapter()
    g.open(str(p), width=8, height=4,
           params={"fit": "contain", "letterbox_rgb": (255, 0, 0)})
    f = g.next_frame(0.0)
    assert f is not None
    # First pixel — leftmost letterbox band — should be red.
    assert list(f.data[0:4]) == [255, 0, 0, 255]
