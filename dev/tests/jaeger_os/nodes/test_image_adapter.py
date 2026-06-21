"""Tests for the ImageAdapter — L1 STATIC animation level.

Exercises the open/close/next_frame Protocol surface with real PNGs
generated in-test via Pillow so no fixture image management
overhead.  Adapter contract:

  open()       → load + fit
  next_frame() → return the one held frame, then None
  close()      → clear buffer + asset state
  skill_id     → "animation.image"
  level        → 1
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from jaeger_os.nodes.software.animation.adapters import ImageAdapter


# ── fixtures ──────────────────────────────────────────────────────

def _png(tmp_path: Path, *, name: str, w: int, h: int,
         color: tuple = (255, 0, 0, 255)) -> Path:
    p = tmp_path / name
    Image.new("RGBA", (w, h), color).save(p)
    return p


# ── identity / metadata ───────────────────────────────────────────

def test_adapter_advertises_skill_id_and_level() -> None:
    adapter = ImageAdapter()
    assert adapter.skill_id == "animation.image"
    assert adapter.level == 1


# ── open + next_frame happy path ──────────────────────────────────

def test_open_and_emit_one_frame(tmp_path: Path) -> None:
    src = _png(tmp_path, name="solid.png", w=8, h=4)
    adapter = ImageAdapter()
    adapter.open(str(src), width=8, height=4, params={})
    frame = adapter.next_frame(0.0)
    assert frame is not None
    assert frame.width == 8
    assert frame.height == 4
    assert len(frame.data) == 8 * 4 * 4  # RGBA
    assert frame.is_final


def test_second_call_returns_none(tmp_path: Path) -> None:
    """Static image: one frame, then None.  AnimationNode honours
    duration_ms separately."""
    src = _png(tmp_path, name="solid.png", w=4, h=4)
    adapter = ImageAdapter()
    adapter.open(str(src), width=4, height=4, params={})
    assert adapter.next_frame(0.0) is not None
    assert adapter.next_frame(0.1) is None
    assert adapter.next_frame(99.0) is None


def test_close_clears_buffer_and_resets(tmp_path: Path) -> None:
    src = _png(tmp_path, name="solid.png", w=4, h=4)
    adapter = ImageAdapter()
    adapter.open(str(src), width=4, height=4, params={})
    adapter.close()
    assert adapter.next_frame(0.0) is None


# ── fit modes ─────────────────────────────────────────────────────

def test_contain_fit_letterboxes(tmp_path: Path) -> None:
    """A square image fitting into a wide target gets centered with
    letterbox bars on the sides."""
    src = _png(tmp_path, name="square.png",
               w=10, h=10, color=(0, 0, 0, 255))
    adapter = ImageAdapter()
    adapter.open(str(src), width=20, height=10,
                 params={"fit": "contain",
                         "letterbox_rgb": (255, 0, 0)})
    frame = adapter.next_frame(0.0)
    assert frame is not None
    # First column should be red letterbox; centre column black.
    pixels = list(frame.data)
    # Pixel at (0, 0) — top-left, RGBA — should be RED.
    assert pixels[0:4] == [255, 0, 0, 255]
    # Pixel at column 10 (centre), row 5 → idx (5*20 + 10)*4 → 440.
    idx = (5 * 20 + 10) * 4
    assert pixels[idx:idx + 4] == [0, 0, 0, 255]


def test_fill_stretches_exactly(tmp_path: Path) -> None:
    src = _png(tmp_path, name="solid.png",
               w=1, h=1, color=(0, 200, 100, 255))
    adapter = ImageAdapter()
    adapter.open(str(src), width=16, height=16,
                 params={"fit": "fill"})
    frame = adapter.next_frame(0.0)
    assert frame is not None
    assert len(frame.data) == 16 * 16 * 4
    # Every pixel should match the source colour.
    px = list(frame.data[:4])
    assert px[1] >= 190 and px[2] >= 90  # allow some resize jitter


def test_unknown_fit_falls_back_to_contain(tmp_path: Path) -> None:
    """Bogus fit mode should not crash; the adapter falls back to
    contain (safe default)."""
    src = _png(tmp_path, name="solid.png", w=4, h=4)
    adapter = ImageAdapter()
    adapter.open(str(src), width=4, height=4,
                 params={"fit": "elastic-banana"})
    assert adapter.next_frame(0.0) is not None


# ── re-open swaps assets cleanly ──────────────────────────────────

def test_reopen_replaces_buffer(tmp_path: Path) -> None:
    a = _png(tmp_path, name="a.png",
             w=4, h=4, color=(255, 0, 0, 255))
    b = _png(tmp_path, name="b.png",
             w=4, h=4, color=(0, 255, 0, 255))
    adapter = ImageAdapter()
    adapter.open(str(a), width=4, height=4, params={"fit": "fill"})
    f1 = adapter.next_frame(0.0)
    adapter.open(str(b), width=4, height=4, params={"fit": "fill"})
    f2 = adapter.next_frame(0.0)
    assert f1 is not None and f2 is not None
    # Frame 1 first pixel should be reddish; frame 2 greenish.
    assert f1.data[0] > f1.data[1]
    assert f2.data[1] > f2.data[0]
