"""Tests for the BitmapAdapter — L1 STATIC monochrome bitmap level."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jaeger_os.nodes.animation.adapters import BitmapAdapter


def _bitmap_json(tmp_path: Path, *, w: int, h: int,
                 data: list[int]) -> Path:
    p = tmp_path / "bm.json"
    p.write_text(json.dumps({
        "width": w, "height": h, "data": data,
    }))
    return p


# ── identity ──────────────────────────────────────────────────────

def test_adapter_identity() -> None:
    a = BitmapAdapter()
    assert a.skill_id == "animation.bitmap"
    assert a.level == 1


# ── single 8×1 row, all ON ────────────────────────────────────────

def test_all_ones_row_renders_foreground(tmp_path: Path) -> None:
    # 8 wide, 1 tall — single byte 0xFF means all 8 bits are 1.
    asset = _bitmap_json(tmp_path, w=8, h=1, data=[0xFF])
    a = BitmapAdapter()
    a.open(str(asset), width=8, height=1,
           params={"fg_rgb": (255, 100, 50), "bg_rgb": (0, 0, 0)})
    f = a.next_frame(0.0)
    assert f is not None
    # All 8 pixels should be foreground.
    for i in range(8):
        offset = i * 4
        assert list(f.data[offset:offset + 4]) == [255, 100, 50, 255]


# ── single 8×1 row, all OFF ───────────────────────────────────────

def test_all_zeros_row_renders_background(tmp_path: Path) -> None:
    asset = _bitmap_json(tmp_path, w=8, h=1, data=[0x00])
    a = BitmapAdapter()
    a.open(str(asset), width=8, height=1,
           params={"fg_rgb": (255, 255, 255),
                   "bg_rgb": (40, 60, 80)})
    f = a.next_frame(0.0)
    assert f is not None
    for i in range(8):
        offset = i * 4
        assert list(f.data[offset:offset + 4]) == [40, 60, 80, 255]


# ── centring in oversized canvas ─────────────────────────────────

def test_bitmap_centred_in_oversized_canvas(tmp_path: Path) -> None:
    """A 2×2 bitmap on a 8×8 canvas should sit in the centre."""
    # 0b11000000, 0b11000000 → 2×2 ON in MSB-first packing.
    asset = _bitmap_json(tmp_path, w=2, h=2, data=[0xC0, 0xC0])
    a = BitmapAdapter()
    a.open(str(asset), width=8, height=8,
           params={"fg_rgb": (255, 255, 255),
                   "bg_rgb": (0, 0, 0)})
    f = a.next_frame(0.0)
    assert f is not None
    # Centre 2×2 should be ON (255s); edges should be OFF (0s).
    def pix(x: int, y: int) -> list[int]:
        offset = (y * 8 + x) * 4
        return list(f.data[offset:offset + 4])
    # The 2×2 bitmap centres at (3,3)–(4,4).
    assert pix(3, 3) == [255, 255, 255, 255]
    assert pix(4, 4) == [255, 255, 255, 255]
    # Outside should be black.
    assert pix(0, 0) == [0, 0, 0, 255]
    assert pix(7, 7) == [0, 0, 0, 255]


# ── one-shot semantics ────────────────────────────────────────────

def test_emit_once_then_none(tmp_path: Path) -> None:
    asset = _bitmap_json(tmp_path, w=2, h=2, data=[0xC0, 0xC0])
    a = BitmapAdapter()
    a.open(str(asset), width=4, height=4, params={})
    assert a.next_frame(0.0) is not None
    assert a.next_frame(0.5) is None


# ── degenerate / empty ────────────────────────────────────────────

def test_empty_bitmap_just_fills_with_bg(tmp_path: Path) -> None:
    asset = _bitmap_json(tmp_path, w=0, h=0, data=[])
    a = BitmapAdapter()
    a.open(str(asset), width=4, height=4,
           params={"fg_rgb": (255, 255, 255),
                   "bg_rgb": (10, 20, 30)})
    f = a.next_frame(0.0)
    assert f is not None
    # All pixels should be background.
    for i in range(16):
        offset = i * 4
        assert list(f.data[offset:offset + 4]) == [10, 20, 30, 255]
