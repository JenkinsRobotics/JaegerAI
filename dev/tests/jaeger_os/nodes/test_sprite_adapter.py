"""Tests for the SpriteAdapter — L2 sprite sheet level."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from jaeger_os.nodes.software.animation.adapters import SpriteAdapter


def _sheet(tmp_path: Path) -> Path:
    """16×16 sheet split into four 8×8 quadrants of distinct colours:
        (0,0)–(7,7)   = red
        (8,0)–(15,7)  = green
        (0,8)–(7,15)  = blue
        (8,8)–(15,15) = white
    """
    p = tmp_path / "sheet.png"
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
    pixels = img.load()
    for y in range(16):
        for x in range(16):
            if x < 8 and y < 8:
                pixels[x, y] = (255, 0, 0, 255)
            elif x >= 8 and y < 8:
                pixels[x, y] = (0, 255, 0, 255)
            elif x < 8 and y >= 8:
                pixels[x, y] = (0, 0, 255, 255)
            else:
                pixels[x, y] = (255, 255, 255, 255)
    img.save(p)
    return p


# ── identity ──────────────────────────────────────────────────────

def test_adapter_identity() -> None:
    a = SpriteAdapter()
    assert a.skill_id == "animation.sprite"
    assert a.level == 2


# ── crop quadrants ────────────────────────────────────────────────

def test_crops_top_left_quadrant(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    a.open(str(sheet), width=8, height=8,
           params={"src": (0, 0, 8, 8)})
    f = a.next_frame(0.0)
    assert f is not None
    # First pixel should be red (top-left of red quadrant).
    assert list(f.data[0:4]) == [255, 0, 0, 255]


def test_crops_bottom_right_quadrant(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    a.open(str(sheet), width=8, height=8,
           params={"src": (8, 8, 8, 8)})
    f = a.next_frame(0.0)
    assert f is not None
    # First pixel should be white (top-left of white quadrant).
    assert list(f.data[0:4]) == [255, 255, 255, 255]


# ── string src form (mscript-compile compatibility) ──────────────

def test_src_accepts_comma_string(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    a.open(str(sheet), width=8, height=8,
           params={"src": "8, 0, 8, 8"})
    f = a.next_frame(0.0)
    assert f is not None
    # Green quadrant.
    assert list(f.data[0:4]) == [0, 255, 0, 255]


# ── centering on oversized canvas ────────────────────────────────

def test_sprite_centred_in_larger_canvas(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    a.open(str(sheet), width=16, height=16,
           params={"src": (0, 0, 8, 8),
                   "bg_rgb": (50, 50, 50)})
    f = a.next_frame(0.0)
    assert f is not None
    # Top-left corner (0,0) should be background grey.
    assert list(f.data[0:4]) == [50, 50, 50, 255]
    # Centre pixel — (8, 8) — falls inside the red sprite.
    centre_idx = (8 * 16 + 8) * 4
    assert list(f.data[centre_idx:centre_idx + 4]) == [255, 0, 0, 255]


# ── error cases ───────────────────────────────────────────────────

def test_missing_src_raises(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    with pytest.raises(ValueError):
        a.open(str(sheet), width=8, height=8, params={})


def test_bad_string_src_raises(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    with pytest.raises(ValueError):
        a.open(str(sheet), width=8, height=8,
               params={"src": "not-coords"})


# ── one-shot semantics ────────────────────────────────────────────

def test_emit_once_then_none(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    a = SpriteAdapter()
    a.open(str(sheet), width=8, height=8,
           params={"src": (0, 0, 8, 8)})
    assert a.next_frame(0.0) is not None
    assert a.next_frame(0.1) is None
