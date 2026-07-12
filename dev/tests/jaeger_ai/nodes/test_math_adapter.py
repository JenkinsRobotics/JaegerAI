"""Tests for the MathAdapter — L4 procedural animation level.

Writes scratch Python scripts under tmp_path so we exercise the
real importlib loading path without permanent fixtures.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from jaeger_ai.nodes.animation.adapters import MathAdapter, MathScript


def _script(tmp_path: Path, *, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(body))
    return p


# ── identity ──────────────────────────────────────────────────────

def test_adapter_identity() -> None:
    a = MathAdapter()
    assert a.skill_id == "animation.math"
    assert a.level == 4


# ── loader ────────────────────────────────────────────────────────

def test_loader_finds_mathscript_subclass(tmp_path: Path) -> None:
    asset = _script(tmp_path, name="solid_red.py", body="""
        from jaeger_ai.nodes.animation.adapters import MathScript

        class SolidRed(MathScript):
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 0] = 200  # R
                frame_rgb[..., 1] = 0    # G
                frame_rgb[..., 2] = 0    # B
    """)
    a = MathAdapter()
    a.open(str(asset), width=4, height=4,
           params={"fps": 30})
    f = a.next_frame(0.0)
    assert f is not None
    # First pixel: RGBA — R=200, G=0, B=0, A=255.
    assert list(f.data[0:4]) == [200, 0, 0, 255]


def test_loader_raises_when_no_subclass(tmp_path: Path) -> None:
    asset = _script(tmp_path, name="not_a_script.py", body="""
        # No MathScript subclass here.
        SOMETHING = 42
    """)
    a = MathAdapter()
    with pytest.raises(ValueError):
        a.open(str(asset), width=4, height=4, params={})


# ── time delta progression ────────────────────────────────────────

def test_animation_can_react_to_time(tmp_path: Path) -> None:
    """Script colours red by time mod 256; first vs later frame
    should differ when t advances."""
    asset = _script(tmp_path, name="time_red.py", body="""
        from jaeger_ai.nodes.animation.adapters import MathScript

        class TimeRed(MathScript):
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 0] = int(t * 100) % 256
    """)
    a = MathAdapter()
    a.open(str(asset), width=4, height=4, params={})
    # First call: t=0 → R=0.  Second: t passed as +1.0 from open.
    a.next_frame(0.0)
    f2 = a.next_frame(1.0)
    assert f2 is not None
    assert f2.data[0] != 0


# ── on_enter is called with params ────────────────────────────────

def test_on_enter_receives_params(tmp_path: Path) -> None:
    asset = _script(tmp_path, name="param_red.py", body="""
        from jaeger_ai.nodes.animation.adapters import MathScript

        class ParamRed(MathScript):
            def on_enter(self, **kwargs):
                self.r = int(kwargs.get('intensity', 0))
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 0] = self.r
    """)
    a = MathAdapter()
    a.open(str(asset), width=4, height=4,
           params={"intensity": 175})
    f = a.next_frame(0.0)
    assert f is not None
    assert f.data[0] == 175


# ── exception in render is tolerated, returns None ───────────────

def test_render_exception_returns_none(tmp_path: Path) -> None:
    asset = _script(tmp_path, name="broken.py", body="""
        from jaeger_ai.nodes.animation.adapters import MathScript

        class Broken(MathScript):
            def render_into(self, t, frame_rgb):
                raise RuntimeError("intentional")
    """)
    a = MathAdapter()
    a.open(str(asset), width=4, height=4, params={})
    assert a.next_frame(0.0) is None


# ── close clears state ────────────────────────────────────────────

def test_close_drops_script(tmp_path: Path) -> None:
    asset = _script(tmp_path, name="solid.py", body="""
        from jaeger_ai.nodes.animation.adapters import MathScript

        class Solid(MathScript):
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 0] = 100
    """)
    a = MathAdapter()
    a.open(str(asset), width=4, height=4, params={})
    a.next_frame(0.0)
    a.close()
    assert a.next_frame(0.0) is None


# ── FPS knob ──────────────────────────────────────────────────────

def test_fps_sets_frame_duration(tmp_path: Path) -> None:
    asset = _script(tmp_path, name="solid.py", body="""
        from jaeger_ai.nodes.animation.adapters import MathScript

        class Solid(MathScript):
            def render_into(self, t, frame_rgb):
                frame_rgb[..., 1] = 200
    """)
    a = MathAdapter()
    a.open(str(asset), width=4, height=4, params={"fps": 60})
    f = a.next_frame(0.0)
    assert f is not None
    # 60 fps → ~17 ms per frame.
    assert 15 <= f.duration_ms <= 19
